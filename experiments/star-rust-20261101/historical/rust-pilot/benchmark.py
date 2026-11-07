"""Synthetic same-machine benchmark. No model inference or STAR service calls.

Measures Python rank fusion, Rust kernel time, amortized subprocess wall time,
and a new-process-per-call cost. Never confuse these with end-to-end AI speed.
"""
from __future__ import annotations
import argparse
import json
import math
import platform
import random
import statistics
import subprocess
import time
from pathlib import Path


def python_fuse(rankings: list[list[int]]) -> list[tuple[int, float]]:
    fused: dict[int, float] = {}
    for number, ranking in enumerate(rankings):
        weight = 2.0 if number == 0 else 1.0
        for rank, chunk_id in enumerate(ranking, 1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + weight / (60 + rank)
    return sorted(fused.items(), key=lambda item: -item[1])


def native(executable: Path, rankings: list[list[int]], repeat: int = 1):
    payload='\n'.join(','.join(str(x) for x in row) for row in rankings)
    start=time.perf_counter()
    result=subprocess.run([str(executable),'--repeat',str(repeat)],input=payload,
                          text=True,capture_output=True,timeout=30,check=True)
    wall=time.perf_counter()-start
    rows=[(int(line.split('\t')[0]),float(line.split('\t')[1]))
          for line in result.stdout.splitlines() if line.strip()]
    metrics=json.loads(result.stderr.strip())
    return rows,metrics['kernel_seconds']/repeat,wall/repeat


def check_equal(expected,actual):
    assert [x[0] for x in expected] == [x[0] for x in actual], 'ranking mismatch'
    assert all(math.isclose(a[1],b[1],rel_tol=1e-14,abs_tol=1e-15)
               for a,b in zip(expected,actual)), 'score mismatch'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); exe=args.exe.resolve()
    rng=random.Random(10530)
    cases=[[],[[]],[[],[20],[10]],[[7,7]],[[1,2],[2,3],[2,4]],[[-1,2],[3]]]
    for _ in range(34):
        cases.append([[rng.randrange(-50,100) for _ in range(rng.randrange(0,50))]
                      for _ in range(rng.randrange(1,10))])
    for rankings in cases:
        result,_,_=native(exe,rankings); check_equal(python_fuse(rankings),result)
    report={'kind':'synthetic_rank_fusion_NOT_ai_benchmark','platform':platform.platform(),
            'python':platform.python_version(),'processor':platform.processor(),
            'parity_cases_passed':len(cases),'samples_per_case':5,'results':[]}
    for n,repeat in ((50,500),(500,100),(5000,10)):
        rankings=[[(i*7+j*13)%(n*3+1) for i in range(n)] for j in range(7)]
        expected=python_fuse(rankings); py=[]; kernel=[]; batch=[]; process=[]
        for sample in range(5):
            # Alternate order to reduce one-sided warmup/thermal bias.
            def py_run():
                start=time.perf_counter()
                for _ in range(repeat): out=python_fuse(rankings)
                py.append((time.perf_counter()-start)/repeat)
                check_equal(expected,out)
            def rust_run():
                out,k,b=native(exe,rankings,repeat)
                check_equal(expected,out); kernel.append(k); batch.append(b)
            if sample%2: rust_run();py_run()
            else: py_run();rust_run()
            out,_,cold=native(exe,rankings);check_equal(expected,out);process.append(cold)
        p=statistics.median(py); k=statistics.median(kernel)
        report['results'].append({'rankings':7,'entries_per_ranking':n,'repeat':repeat,
            'python_median_ms':p*1000,'rust_kernel_median_ms':k*1000,
            'kernel_speedup':p/k,'rust_amortized_process_ms':statistics.median(batch)*1000,
            'rust_new_process_per_call_ms':statistics.median(process)*1000,
            'python_samples_ms':[x*1000 for x in py],
            'rust_kernel_samples_ms':[x*1000 for x in kernel]})
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
