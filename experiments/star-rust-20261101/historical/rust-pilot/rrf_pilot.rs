//! Experimental rank-fusion kernel, NOT an installed STAR backend.
//! Matches STAR merge_facets(..., how="rrf"): whole query weight 2,
//! other rankings weight 1, K=60, and first-seen order for exact score ties.
#![forbid(unsafe_code)]
use std::collections::HashMap;
use std::io::{self, Read};
use std::time::Instant;

const MAX_BYTES: u64 = 2_000_000;
const MAX_RANKINGS: usize = 16;
const MAX_PER_RANKING: usize = 20_000;
const MAX_TOTAL: usize = 100_000;

fn parse(input: &str) -> Result<Vec<Vec<i64>>, &'static str> {
    let mut rankings = Vec::new();
    let mut total = 0;
    for line in input.split('\n') {
        if rankings.len() == MAX_RANKINGS { return Err("too many rankings"); }
        let line = line.trim();
        let mut ranking = Vec::new();
        if !line.is_empty() {
            for item in line.split(',') {
                if ranking.len() == MAX_PER_RANKING { return Err("ranking too large"); }
                total += 1;
                if total > MAX_TOTAL { return Err("too many entries"); }
                ranking.push(item.trim().parse::<i64>().map_err(|_| "invalid integer id")?);
            }
        }
        rankings.push(ranking);
    }
    Ok(rankings)
}

fn fuse(rankings: &[Vec<i64>]) -> Vec<(i64, f64)> {
    let mut positions: HashMap<i64, usize> = HashMap::new();
    let mut scores: Vec<(i64, f64)> = Vec::new();
    for (number, ranking) in rankings.iter().enumerate() {
        let weight = if number == 0 { 2.0 } else { 1.0 };
        for (index, id) in ranking.iter().enumerate() {
            let position = *positions.entry(*id).or_insert_with(|| {
                scores.push((*id, 0.0));
                scores.len() - 1
            });
            scores[position].1 += weight / (61.0 + index as f64);
        }
    }
    // Stable sort is intentional: ties match Python dict first-seen order.
    scores.sort_by(|a, b| b.1.total_cmp(&a.1));
    scores
}

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let repeat: usize = match args.as_slice() {
        [] => 1,
        [flag, value] if flag == "--repeat" => value.parse().map_err(|_| "invalid repeat")?,
        _ => return Err("usage: rrf_pilot [--repeat N] < rankings.txt".into()),
    };
    if !(1..=10_000).contains(&repeat) { return Err("repeat must be 1..10000".into()); }
    let mut raw = Vec::new();
    io::stdin().take(MAX_BYTES + 1).read_to_end(&mut raw).map_err(|_| "input read failed")?;
    if raw.len() as u64 > MAX_BYTES { return Err("input too large".into()); }
    let input = std::str::from_utf8(&raw).map_err(|_| "input is not UTF-8")?;
    let rankings = parse(input).map_err(str::to_string)?;
    let start = Instant::now();
    let mut output = Vec::new();
    for _ in 0..repeat { output = std::hint::black_box(fuse(std::hint::black_box(&rankings))); }
    let elapsed = start.elapsed().as_secs_f64();
    eprintln!("{{\"repeat\":{},\"kernel_seconds\":{:.9}}}", repeat, elapsed);
    for (id, score) in output { println!("{}\t{:.17}", id, score); }
    Ok(())
}

fn main() {
    if let Err(error) = run() { eprintln!("pilot error: {}", error); std::process::exit(2); }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn empty() { assert!(fuse(&parse("").unwrap()).is_empty()); }
    #[test] fn whole_query_has_weight_two() {
        let rows=fuse(&parse("10\n20").unwrap());
        assert_eq!(rows[0].0,10); assert!((rows[0].1-2.0/61.0).abs()<1e-15);
    }
    #[test] fn ties_use_first_seen_order() {
        let rows=fuse(&parse("\n20\n10").unwrap());
        assert_eq!(rows.iter().map(|r|r.0).collect::<Vec<_>>(),vec![20,10]);
    }
    #[test] fn duplicate_occurrences_keep_original_semantics() {
        let rows=fuse(&parse("7,7").unwrap());
        assert_eq!(rows.len(),1); assert!((rows[0].1-(2.0/61.0+2.0/62.0)).abs()<1e-15);
    }
    #[test] fn combines_queries() {
        assert_eq!(fuse(&parse("1,2\n2,3\n2,4").unwrap())[0].0,2);
    }
    #[test] fn rejects_non_integer() { assert!(parse("1,foo").is_err()); }
    #[test] fn rejects_too_many_rankings() { assert!(parse(&"\n".repeat(16)).is_err()); }
    #[test] fn rejects_oversized_ranking() {
        assert!(parse(&vec!["1";MAX_PER_RANKING+1].join(",")).is_err());
    }
    #[test] fn signed_ids_and_crlf() { assert_eq!(parse("-1,2\r\n3").unwrap(),vec![vec![-1,2],vec![3]]); }
}
