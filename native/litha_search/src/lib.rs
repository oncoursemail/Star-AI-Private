//! Immutable, exact inner-product search; no threads, network, GPU or subprocesses.
//!
//! SQLite embeddings use the existing builder's native-endian float32 format.
//! Query normalization stays in Python to preserve the current model contract.
use pyo3::exceptions::{PyMemoryError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyTuple};
use std::cmp::Ordering;
use std::collections::BinaryHeap;

const MAX_DIMENSION: usize = 65_536;
const MAX_ROWS: usize = 1_000_000;
const DEFAULT_MAX_BYTES: usize = 512 * 1024 * 1024;

#[derive(Clone, Copy, Debug)]
struct Hit {
    row: usize,
    score: f64,
}

// The heap root is the WORST retained hit: lower score, then later corpus row.
impl Ord for Hit {
    fn cmp(&self, other: &Self) -> Ordering {
        other
            .score
            .partial_cmp(&self.score)
            .expect("finite dot product")
            .then_with(|| self.row.cmp(&other.row))
    }
}
impl PartialOrd for Hit {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl PartialEq for Hit {
    fn eq(&self, other: &Self) -> bool {
        self.row == other.row && self.score == other.score
    }
}
impl Eq for Hit {}

fn dot(query: &[f32], vector: &[f32]) -> f64 {
    // Each f32 product is exact in f64. Compensated accumulation limits drift
    // against Python 3.12 math.sumprod (extended precision). No fast-math/FMA.
    let mut sum = 0.0_f64;
    let mut correction = 0.0_f64;
    for (&q, &v) in query.iter().zip(vector) {
        let product = f64::from(q) * f64::from(v);
        let next = sum + product;
        correction += if sum.abs() >= product.abs() {
            (sum - next) + product
        } else {
            (product - next) + sum
        };
        sum = next;
    }
    sum + correction
}

#[pyclass(frozen)]
struct DenseIndex {
    ids: Vec<i64>,
    vectors: Vec<f32>,
    #[pyo3(get)]
    dimension: usize,
    #[pyo3(get)]
    skipped_rows: usize,
}

impl DenseIndex {
    fn top_k(&self, query: &[f32], k: usize) -> Vec<(i64, f64)> {
        let limit = k.min(self.ids.len());
        if limit == 0 || self.dimension == 0 {
            return Vec::new();
        }
        let mut heap = BinaryHeap::with_capacity(limit);
        for (row, vector) in self.vectors.chunks_exact(self.dimension).enumerate() {
            let hit = Hit {
                row,
                score: dot(query, vector),
            };
            if heap.len() < limit {
                heap.push(hit);
            } else if let Some(mut worst) = heap.peek_mut() {
                if hit < *worst {
                    *worst = hit;
                }
            }
        }
        let mut hits = heap.into_vec();
        hits.sort_unstable();
        hits.into_iter()
            .map(|hit| (self.ids[hit.row], hit.score))
            .collect()
    }
}

#[pymethods]
impl DenseIndex {
    #[new]
    #[pyo3(signature = (rows, max_bytes=DEFAULT_MAX_BYTES))]
    fn new(rows: &Bound<'_, PyAny>, max_bytes: usize) -> PyResult<Self> {
        if max_bytes == 0 {
            return Err(PyValueError::new_err("max_bytes must be positive"));
        }
        let mut out = Self {
            ids: Vec::new(),
            vectors: Vec::new(),
            dimension: 0,
            skipped_rows: 0,
        };
        // Iteration consumes a SQLite cursor one row at a time, never a Python
        // copy of the entire corpus. Values are copied once into packed f32s.
        for (seen, record) in rows.try_iter()?.enumerate() {
            if seen >= MAX_ROWS {
                return Err(PyValueError::new_err("dense vector row limit exceeded"));
            }
            let record = record?;
            let tuple = record.cast::<PyTuple>()?;
            if tuple.len() != 2 {
                return Err(PyValueError::new_err(
                    "expected (passage_id, float32_bytes)",
                ));
            }
            let id = tuple.get_item(0)?.extract::<i64>()?;
            let value = tuple.get_item(1)?;
            let Ok(bytes) = value.cast::<PyBytes>() else {
                out.skipped_rows += 1;
                continue;
            };
            let bytes = bytes.as_bytes();
            let dim = bytes.len() / 4;
            if bytes.len() % 4 != 0
                || dim == 0
                || dim > MAX_DIMENSION
                || (out.dimension != 0 && out.dimension != dim)
                || bytes.chunks_exact(4).any(|b| {
                    !f32::from_ne_bytes(b.try_into().expect("four-byte chunk")).is_finite()
                })
            {
                out.skipped_rows += 1;
                continue;
            }
            let needed = out
                .vectors
                .len()
                .checked_add(dim)
                .and_then(|n| n.checked_mul(4))
                .and_then(|n| n.checked_add((out.ids.len() + 1) * 8));
            if needed.is_none_or(|n| n > max_bytes) {
                return Err(PyValueError::new_err(
                    "dense vector payload budget exceeded",
                ));
            }
            out.ids
                .try_reserve(1)
                .map_err(|_| PyMemoryError::new_err("cannot reserve vector IDs"))?;
            out.vectors
                .try_reserve(dim)
                .map_err(|_| PyMemoryError::new_err("cannot reserve vectors"))?;
            out.dimension = dim;
            out.ids.push(id);
            out.vectors.extend(
                bytes
                    .chunks_exact(4)
                    .map(|b| f32::from_ne_bytes(b.try_into().expect("four-byte chunk"))),
            );
        }
        out.ids.shrink_to_fit();
        out.vectors.shrink_to_fit();
        Ok(out)
    }

    #[getter]
    fn count(&self) -> usize {
        self.ids.len()
    }

    #[getter]
    fn storage_bytes(&self) -> usize {
        self.ids.len() * 8 + self.vectors.len() * 4
    }

    #[pyo3(signature = (query, k=8))]
    fn search(
        &self,
        py: Python<'_>,
        query: &Bound<'_, PyBytes>,
        k: usize,
    ) -> PyResult<Vec<(i64, f64)>> {
        let bytes = query.as_bytes();
        if bytes.len() != self.dimension * 4 {
            return Err(PyValueError::new_err("query dimension differs from index"));
        }
        let query: Vec<f32> = bytes
            .chunks_exact(4)
            .map(|b| f32::from_ne_bytes(b.try_into().expect("four-byte chunk")))
            .collect();
        if query.iter().any(|x| !x.is_finite()) {
            return Err(PyValueError::new_err("query must be finite"));
        }
        // The immutable index can be queried by multiple service threads. No
        // Python object is accessed while detached, and only O(k) hits survive.
        Ok(py.detach(|| self.top_k(&query, k)))
    }
}

#[pymodule]
fn litha_search(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<DenseIndex>()?;
    module.add("API_VERSION", 1)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn heap_keeps_best_and_stable_ties() {
        let idx = DenseIndex {
            ids: vec![99, 7, 4, 9, 8],
            vectors: vec![0.0, 1.0, 1.0, -1.0, 0.5],
            dimension: 1,
            skipped_rows: 0,
        };
        assert_eq!(idx.top_k(&[1.0], 2), vec![(7, 1.0), (4, 1.0)]);
        assert_eq!(idx.top_k(&[0.0], 3), vec![(99, 0.0), (7, 0.0), (4, 0.0)]);
        assert!(idx.top_k(&[1.0], 0).is_empty());
    }

    #[test]
    fn compensated_dot_preserves_small_term_between_large_terms() {
        assert_eq!(dot(&[1.0, 1.0, 1.0], &[1e20, 1.0, -1e20]), 1.0);
    }
}
