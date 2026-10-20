"""The problem bank: small, language-neutral functions with a Python oracle (test cases) and a reference solution in
every judge language. JavaScript references are derived from the TypeScript ones by the judge (recipe ts2js)."""
from __future__ import annotations

import math
import random

# (fn, params, ret, family, description, oracle, references)
PROBLEMS: list[dict] = []


def problem(fn, params, ret, family, desc, oracle, cases, **refs):
    PROBLEMS.append({"fn": fn, "params": params, "ret": ret, "family": family, "desc": desc, "oracle": oracle,
                     "cases": cases, "refs": refs})


def _rng(name):
    return random.Random("multi-school-" + name)


# --- 1 clamp --------------------------------------------------------------------------------------------------
def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


r = _rng("clamp")
problem("clamp", [("x", "float"), ("lo", "float"), ("hi", "float")], "float", "game-math",
        "Return `x` limited to the closed range [`lo`, `hi`].", _clamp,
        [((5.0, 0.0, 10.0),), ((-3.5, 0.0, 10.0),), ((12.0, 0.0, 10.0),), ((0.0, 0.0, 0.0),), ((7.25, 7.0, 7.5),)]
        + [((r.uniform(-20, 20), -5.0, 5.0),) for _ in range(3)],
        python="def clamp(x, lo, hi):\n    return max(lo, min(hi, x))\n",
        typescript="function clamp(x: number, lo: number, hi: number): number {\n    return Math.max(lo, Math.min(hi, x));\n}\n",
        cpp="#include <algorithm>\ndouble clamp(double x, double lo, double hi) {\n    return std::max(lo, std::min(hi, x));\n}\n",
        csharp="public static double Clamp(double x, double lo, double hi) {\n    return Math.Max(lo, Math.Min(hi, x));\n}\n",
        java="public static double clamp(double x, double lo, double hi) {\n    return Math.max(lo, Math.min(hi, x));\n}\n",
        go="func Clamp(x, lo, hi float64) float64 {\n\tif x < lo {\n\t\treturn lo\n\t}\n\tif x > hi {\n\t\treturn hi\n\t}\n\treturn x\n}\n",
        rust="fn clamp(x: f64, lo: f64, hi: f64) -> f64 {\n    if x < lo { lo } else if x > hi { hi } else { x }\n}\n",
        lua="function clamp(x, lo, hi)\n    return math.max(lo, math.min(hi, x))\nend\n",
        gdscript="static func clamp(x: float, lo: float, hi: float) -> float:\n\treturn maxf(lo, minf(hi, x))\n")

# --- 2 lerp ---------------------------------------------------------------------------------------------------
def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t


r = _rng("lerp")
problem("lerp", [("a", "float"), ("b", "float"), ("t", "float")], "float", "game-math",
        "Linear interpolation from `a` to `b` by `t`, with `t` clamped to [0, 1] first.", _lerp,
        [((0.0, 10.0, 0.5),), ((0.0, 10.0, 1.5),), ((0.0, 10.0, -1.0),), ((5.0, -5.0, 0.25),)]
        + [((r.uniform(-9, 9), r.uniform(-9, 9), r.uniform(-0.5, 1.5)),) for _ in range(4)],
        python="def lerp(a, b, t):\n    t = max(0.0, min(1.0, t))\n    return a + (b - a) * t\n",
        typescript="function lerp(a: number, b: number, t: number): number {\n    t = Math.max(0, Math.min(1, t));\n    return a + (b - a) * t;\n}\n",
        cpp="double lerp(double a, double b, double t) {\n    if (t < 0) t = 0;\n    if (t > 1) t = 1;\n    return a + (b - a) * t;\n}\n",
        csharp="public static double Lerp(double a, double b, double t) {\n    t = Math.Max(0, Math.Min(1, t));\n    return a + (b - a) * t;\n}\n",
        java="public static double lerp(double a, double b, double t) {\n    t = Math.max(0, Math.min(1, t));\n    return a + (b - a) * t;\n}\n",
        go="func Lerp(a, b, t float64) float64 {\n\tif t < 0 {\n\t\tt = 0\n\t}\n\tif t > 1 {\n\t\tt = 1\n\t}\n\treturn a + (b-a)*t\n}\n",
        rust="fn lerp(a: f64, b: f64, t: f64) -> f64 {\n    let t = t.max(0.0).min(1.0);\n    a + (b - a) * t\n}\n",
        lua="function lerp(a, b, t)\n    t = math.max(0, math.min(1, t))\n    return a + (b - a) * t\nend\n",
        gdscript="static func lerp(a: float, b: float, t: float) -> float:\n\tt = clampf(t, 0.0, 1.0)\n\treturn a + (b - a) * t\n")

# --- 3 gcd ----------------------------------------------------------------------------------------------------
problem("gcd", [("a", "int"), ("b", "int")], "int", "algorithms",
        "Greatest common divisor of two non-negative integers (gcd(0, b) = b).", math.gcd,
        [((12, 18),), ((7, 13),), ((0, 9),), ((100, 75),), ((36, 60),), ((1071, 462),), ((5, 0),), ((48, 180),)],
        python="def gcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a\n",
        typescript="function gcd(a: number, b: number): number {\n    while (b !== 0) {\n        const t = a % b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",
        cpp="int gcd(int a, int b) {\n    while (b != 0) {\n        int t = a % b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",
        csharp="public static int Gcd(int a, int b) {\n    while (b != 0) {\n        int t = a % b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",
        java="public static int gcd(int a, int b) {\n    while (b != 0) {\n        int t = a % b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",
        go="func Gcd(a, b int) int {\n\tfor b != 0 {\n\t\ta, b = b, a%b\n\t}\n\treturn a\n}\n",
        rust="fn gcd(a: i64, b: i64) -> i64 {\n    let (mut a, mut b) = (a, b);\n    while b != 0 {\n        let t = a % b;\n        a = b;\n        b = t;\n    }\n    a\n}\n",
        lua="function gcd(a, b)\n    while b ~= 0 do\n        a, b = b, a % b\n    end\n    return a\nend\n",
        gdscript="static func gcd(a: int, b: int) -> int:\n\twhile b != 0:\n\t\tvar t = a % b\n\t\ta = b\n\t\tb = t\n\treturn a\n")

# --- 4 is_prime -----------------------------------------------------------------------------------------------
def _is_prime(n):
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


problem("is_prime", [("n", "int")], "bool", "algorithms", "True when `n` is a prime number (n < 2 is not prime).",
        _is_prime, [((2,),), ((1,),), ((0,),), ((17,),), ((18,),), ((97,),), ((100,),), ((7919,),), ((7917,),)],
        python="def is_prime(n):\n    if n < 2:\n        return False\n    i = 2\n    while i * i <= n:\n        if n % i == 0:\n            return False\n        i += 1\n    return True\n",
        typescript="function isPrime(n: number): boolean {\n    if (n < 2) return false;\n    for (let i = 2; i * i <= n; i++) {\n        if (n % i === 0) return false;\n    }\n    return true;\n}\n",
        cpp="bool isPrime(int n) {\n    if (n < 2) return false;\n    for (int i = 2; i * i <= n; ++i) {\n        if (n % i == 0) return false;\n    }\n    return true;\n}\n",
        csharp="public static bool IsPrime(int n) {\n    if (n < 2) return false;\n    for (int i = 2; i * i <= n; i++) {\n        if (n % i == 0) return false;\n    }\n    return true;\n}\n",
        java="public static boolean isPrime(int n) {\n    if (n < 2) return false;\n    for (int i = 2; i * i <= n; i++) {\n        if (n % i == 0) return false;\n    }\n    return true;\n}\n",
        go="func IsPrime(n int) bool {\n\tif n < 2 {\n\t\treturn false\n\t}\n\tfor i := 2; i*i <= n; i++ {\n\t\tif n%i == 0 {\n\t\t\treturn false\n\t\t}\n\t}\n\treturn true\n}\n",
        rust="fn is_prime(n: i64) -> bool {\n    if n < 2 { return false; }\n    let mut i = 2;\n    while i * i <= n {\n        if n % i == 0 { return false; }\n        i += 1;\n    }\n    true\n}\n",
        lua="function is_prime(n)\n    if n < 2 then return false end\n    local i = 2\n    while i * i <= n do\n        if n % i == 0 then return false end\n        i = i + 1\n    end\n    return true\nend\n",
        gdscript="static func is_prime(n: int) -> bool:\n\tif n < 2:\n\t\treturn false\n\tvar i := 2\n\twhile i * i <= n:\n\t\tif n % i == 0:\n\t\t\treturn false\n\t\ti += 1\n\treturn true\n")

# --- 5 fib ----------------------------------------------------------------------------------------------------
def _fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


problem("fib", [("n", "int")], "int", "algorithms", "The n-th Fibonacci number with fib(0) = 0, fib(1) = 1 (0 <= n <= 40).",
        _fib, [((0,),), ((1,),), ((2,),), ((10,),), ((20,),), ((30,),), ((40,),)],
        python="def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n",
        typescript="function fib(n: number): number {\n    let a = 0, b = 1;\n    for (let i = 0; i < n; i++) {\n        const t = a + b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",
        cpp="int fib(int n) {\n    int a = 0, b = 1;\n    for (int i = 0; i < n; ++i) {\n        int t = a + b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",
        csharp="public static int Fib(int n) {\n    int a = 0, b = 1;\n    for (int i = 0; i < n; i++) {\n        int t = a + b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",
        java="public static int fib(int n) {\n    int a = 0, b = 1;\n    for (int i = 0; i < n; i++) {\n        int t = a + b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",
        go="func Fib(n int) int {\n\ta, b := 0, 1\n\tfor i := 0; i < n; i++ {\n\t\ta, b = b, a+b\n\t}\n\treturn a\n}\n",
        rust="fn fib(n: i64) -> i64 {\n    let (mut a, mut b) = (0i64, 1i64);\n    for _ in 0..n {\n        let t = a + b;\n        a = b;\n        b = t;\n    }\n    a\n}\n",
        lua="function fib(n)\n    local a, b = 0, 1\n    for _ = 1, n do\n        a, b = b, a + b\n    end\n    return a\nend\n",
        gdscript="static func fib(n: int) -> int:\n\tvar a := 0\n\tvar b := 1\n\tfor _i in range(n):\n\t\tvar t = a + b\n\t\ta = b\n\t\tb = t\n\treturn a\n")

# --- 6 sum_array ----------------------------------------------------------------------------------------------
r = _rng("sum")
problem("sum_array", [("a", "int[]")], "int", "algorithms", "The sum of all integers in `a` (0 for an empty array).", sum,
        [(([1, 2, 3],),), (([],),), (([-5, 5, 10],),)] + [(([r.randint(-50, 50) for _ in range(r.randint(1, 8))],),) for _ in range(4)],
        python="def sum_array(a):\n    return sum(a)\n",
        typescript="function sumArray(a: number[]): number {\n    return a.reduce((s, x) => s + x, 0);\n}\n",
        cpp="#include <vector>\nint sumArray(const std::vector<int>& a) {\n    int s = 0;\n    for (int x : a) s += x;\n    return s;\n}\n",
        csharp="public static int SumArray(int[] a) {\n    int s = 0;\n    foreach (int x in a) s += x;\n    return s;\n}\n",
        java="public static int sumArray(int[] a) {\n    int s = 0;\n    for (int x : a) s += x;\n    return s;\n}\n",
        go="func SumArray(a []int) int {\n\ts := 0\n\tfor _, x := range a {\n\t\ts += x\n\t}\n\treturn s\n}\n",
        rust="fn sum_array(a: &[i64]) -> i64 {\n    a.iter().sum()\n}\n",
        lua="function sum_array(a)\n    local s = 0\n    for _, x in ipairs(a) do s = s + x end\n    return s\nend\n",
        gdscript="static func sum_array(a: Array) -> int:\n\tvar s := 0\n\tfor x in a:\n\t\ts += x\n\treturn s\n")

# --- 7 max_array ----------------------------------------------------------------------------------------------
r = _rng("max")
problem("max_array", [("a", "int[]")], "int", "algorithms", "The largest integer in the non-empty array `a`.", max,
        [(([1, 5, 3],),), (([-9, -2, -7],),), (([42],),)] + [(([r.randint(-99, 99) for _ in range(r.randint(2, 9))],),) for _ in range(4)],
        python="def max_array(a):\n    best = a[0]\n    for x in a:\n        if x > best:\n            best = x\n    return best\n",
        typescript="function maxArray(a: number[]): number {\n    let best = a[0];\n    for (const x of a) if (x > best) best = x;\n    return best;\n}\n",
        cpp="#include <vector>\nint maxArray(const std::vector<int>& a) {\n    int best = a[0];\n    for (int x : a) if (x > best) best = x;\n    return best;\n}\n",
        csharp="public static int MaxArray(int[] a) {\n    int best = a[0];\n    foreach (int x in a) if (x > best) best = x;\n    return best;\n}\n",
        java="public static int maxArray(int[] a) {\n    int best = a[0];\n    for (int x : a) if (x > best) best = x;\n    return best;\n}\n",
        go="func MaxArray(a []int) int {\n\tbest := a[0]\n\tfor _, x := range a {\n\t\tif x > best {\n\t\t\tbest = x\n\t\t}\n\t}\n\treturn best\n}\n",
        rust="fn max_array(a: &[i64]) -> i64 {\n    *a.iter().max().unwrap()\n}\n",
        lua="function max_array(a)\n    local best = a[1]\n    for _, x in ipairs(a) do if x > best then best = x end end\n    return best\nend\n",
        gdscript="static func max_array(a: Array) -> int:\n\tvar best = a[0]\n\tfor x in a:\n\t\tif x > best:\n\t\t\tbest = x\n\treturn best\n")

# --- 8 reverse_string -----------------------------------------------------------------------------------------
problem("reverse_string", [("s", "str")], "str", "strings", "The characters of `s` in reverse order (ASCII input).",
        lambda s: s[::-1], [(("hello",),), (("",),), (("a",),), (("Star AI",),), (("racecar",),), (("12345",),)],
        python="def reverse_string(s):\n    return s[::-1]\n",
        typescript="function reverseString(s: string): string {\n    return s.split(\"\").reverse().join(\"\");\n}\n",
        cpp="#include <string>\n#include <algorithm>\nstd::string reverseString(const std::string& s) {\n    std::string out = s;\n    std::reverse(out.begin(), out.end());\n    return out;\n}\n",
        csharp="public static string ReverseString(string s) {\n    char[] chars = s.ToCharArray();\n    Array.Reverse(chars);\n    return new string(chars);\n}\n",
        java="public static String reverseString(String s) {\n    return new StringBuilder(s).reverse().toString();\n}\n",
        go="func ReverseString(s string) string {\n\tb := []byte(s)\n\tfor i, j := 0, len(b)-1; i < j; i, j = i+1, j-1 {\n\t\tb[i], b[j] = b[j], b[i]\n\t}\n\treturn string(b)\n}\n",
        rust="fn reverse_string(s: &str) -> String {\n    s.chars().rev().collect()\n}\n",
        lua="function reverse_string(s)\n    return s:reverse()\nend\n",
        gdscript="static func reverse_string(s: String) -> String:\n\tvar out := \"\"\n\tfor i in range(s.length() - 1, -1, -1):\n\t\tout += s[i]\n\treturn out\n")

# --- 9 count_vowels -------------------------------------------------------------------------------------------
problem("count_vowels", [("s", "str")], "int", "strings", "How many characters of `s` are vowels (a, e, i, o, u, either case).",
        lambda s: sum(c in "aeiouAEIOU" for c in s),
        [(("hello",),), (("",),), (("xyz",),), (("AEIOU aeiou",),), (("Programming in Lua",),), (("rhythm",),)],
        python="def count_vowels(s):\n    return sum(1 for c in s if c in \"aeiouAEIOU\")\n",
        typescript="function countVowels(s: string): number {\n    let n = 0;\n    for (const c of s) if (\"aeiouAEIOU\".includes(c)) n++;\n    return n;\n}\n",
        cpp="#include <string>\nint countVowels(const std::string& s) {\n    int n = 0;\n    for (char c : s) if (std::string(\"aeiouAEIOU\").find(c) != std::string::npos) ++n;\n    return n;\n}\n",
        csharp="public static int CountVowels(string s) {\n    int n = 0;\n    foreach (char c in s) if (\"aeiouAEIOU\".IndexOf(c) >= 0) n++;\n    return n;\n}\n",
        java="public static int countVowels(String s) {\n    int n = 0;\n    for (char c : s.toCharArray()) if (\"aeiouAEIOU\".indexOf(c) >= 0) n++;\n    return n;\n}\n",
        go="import \"strings\"\n\nfunc CountVowels(s string) int {\n\tn := 0\n\tfor _, c := range s {\n\t\tif strings.ContainsRune(\"aeiouAEIOU\", c) {\n\t\t\tn++\n\t\t}\n\t}\n\treturn n\n}\n",
        rust="fn count_vowels(s: &str) -> i64 {\n    s.chars().filter(|c| \"aeiouAEIOU\".contains(*c)).count() as i64\n}\n",
        lua="function count_vowels(s)\n    local _, n = s:gsub(\"[aeiouAEIOU]\", \"\")\n    return n\nend\n",
        gdscript="static func count_vowels(s: String) -> int:\n\tvar n := 0\n\tfor c in s:\n\t\tif c in \"aeiouAEIOU\":\n\t\t\tn += 1\n\treturn n\n")

# --- 10 binary_search -----------------------------------------------------------------------------------------
def _bsearch(a, t):
    lo, hi = 0, len(a) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if a[mid] == t:
            return mid
        if a[mid] < t:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


problem("binary_search", [("a", "int[]"), ("target", "int")], "int", "algorithms",
        "Index of `target` in the sorted array `a` using binary search, or -1 when absent.", _bsearch,
        [(([1, 3, 5, 7, 9, 11], 7),), (([1, 3, 5, 7, 9, 11], 1),), (([1, 3, 5, 7, 9, 11], 11),), (([1, 3, 5, 7, 9, 11], 4),),
         (([], 3),), (([2], 2),), (([2], 5),), (([-10, -5, 0, 5, 10, 15, 20, 25], 20),)],
        python="def binary_search(a, target):\n    lo, hi = 0, len(a) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if a[mid] == target:\n            return mid\n        if a[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1\n",
        typescript="function binarySearch(a: number[], target: number): number {\n    let lo = 0, hi = a.length - 1;\n    while (lo <= hi) {\n        const mid = Math.floor((lo + hi) / 2);\n        if (a[mid] === target) return mid;\n        if (a[mid] < target) lo = mid + 1; else hi = mid - 1;\n    }\n    return -1;\n}\n",
        cpp="#include <vector>\nint binarySearch(const std::vector<int>& a, int target) {\n    int lo = 0, hi = (int)a.size() - 1;\n    while (lo <= hi) {\n        int mid = lo + (hi - lo) / 2;\n        if (a[mid] == target) return mid;\n        if (a[mid] < target) lo = mid + 1; else hi = mid - 1;\n    }\n    return -1;\n}\n",
        csharp="public static int BinarySearch(int[] a, int target) {\n    int lo = 0, hi = a.Length - 1;\n    while (lo <= hi) {\n        int mid = lo + (hi - lo) / 2;\n        if (a[mid] == target) return mid;\n        if (a[mid] < target) lo = mid + 1; else hi = mid - 1;\n    }\n    return -1;\n}\n",
        java="public static int binarySearch(int[] a, int target) {\n    int lo = 0, hi = a.length - 1;\n    while (lo <= hi) {\n        int mid = lo + (hi - lo) / 2;\n        if (a[mid] == target) return mid;\n        if (a[mid] < target) lo = mid + 1; else hi = mid - 1;\n    }\n    return -1;\n}\n",
        go="func BinarySearch(a []int, target int) int {\n\tlo, hi := 0, len(a)-1\n\tfor lo <= hi {\n\t\tmid := lo + (hi-lo)/2\n\t\tif a[mid] == target {\n\t\t\treturn mid\n\t\t}\n\t\tif a[mid] < target {\n\t\t\tlo = mid + 1\n\t\t} else {\n\t\t\thi = mid - 1\n\t\t}\n\t}\n\treturn -1\n}\n",
        rust="fn binary_search(a: &[i64], target: i64) -> i64 {\n    let (mut lo, mut hi) = (0i64, a.len() as i64 - 1);\n    while lo <= hi {\n        let mid = lo + (hi - lo) / 2;\n        let v = a[mid as usize];\n        if v == target { return mid; }\n        if v < target { lo = mid + 1; } else { hi = mid - 1; }\n    }\n    -1\n}\n",
        lua="function binary_search(a, target)\n    local lo, hi = 1, #a\n    while lo <= hi do\n        local mid = (lo + hi) // 2\n        if a[mid] == target then return mid - 1 end\n        if a[mid] < target then lo = mid + 1 else hi = mid - 1 end\n    end\n    return -1\nend\n",
        gdscript="static func binary_search(a: Array, target: int) -> int:\n\tvar lo := 0\n\tvar hi := a.size() - 1\n\twhile lo <= hi:\n\t\tvar mid := (lo + hi) / 2\n\t\tif a[mid] == target:\n\t\t\treturn mid\n\t\tif a[mid] < target:\n\t\t\tlo = mid + 1\n\t\telse:\n\t\t\thi = mid - 1\n\treturn -1\n")

# --- 11 max_subarray ------------------------------------------------------------------------------------------
def _kadane(a):
    best = cur = a[0]
    for x in a[1:]:
        cur = max(x, cur + x)
        best = max(best, cur)
    return best


problem("max_subarray", [("a", "int[]")], "int", "algorithms",
        "The largest sum of any non-empty contiguous subarray of `a` (Kadane's algorithm).", _kadane,
        [(([-2, 1, -3, 4, -1, 2, 1, -5, 4],),), (([1],),), (([-3, -1, -2],),), (([5, -2, 5],),), (([2, 3, -10, 4, 5],),), (([-1, 10, -1],),)],
        python="def max_subarray(a):\n    best = cur = a[0]\n    for x in a[1:]:\n        cur = max(x, cur + x)\n        best = max(best, cur)\n    return best\n",
        typescript="function maxSubarray(a: number[]): number {\n    let best = a[0], cur = a[0];\n    for (let i = 1; i < a.length; i++) {\n        cur = Math.max(a[i], cur + a[i]);\n        best = Math.max(best, cur);\n    }\n    return best;\n}\n",
        cpp="#include <vector>\n#include <algorithm>\nint maxSubarray(const std::vector<int>& a) {\n    int best = a[0], cur = a[0];\n    for (size_t i = 1; i < a.size(); ++i) {\n        cur = std::max(a[i], cur + a[i]);\n        best = std::max(best, cur);\n    }\n    return best;\n}\n",
        csharp="public static int MaxSubarray(int[] a) {\n    int best = a[0], cur = a[0];\n    for (int i = 1; i < a.Length; i++) {\n        cur = Math.Max(a[i], cur + a[i]);\n        best = Math.Max(best, cur);\n    }\n    return best;\n}\n",
        java="public static int maxSubarray(int[] a) {\n    int best = a[0], cur = a[0];\n    for (int i = 1; i < a.length; i++) {\n        cur = Math.max(a[i], cur + a[i]);\n        best = Math.max(best, cur);\n    }\n    return best;\n}\n",
        go="func MaxSubarray(a []int) int {\n\tbest, cur := a[0], a[0]\n\tfor _, x := range a[1:] {\n\t\tif cur+x > x {\n\t\t\tcur = cur + x\n\t\t} else {\n\t\t\tcur = x\n\t\t}\n\t\tif cur > best {\n\t\t\tbest = cur\n\t\t}\n\t}\n\treturn best\n}\n",
        rust="fn max_subarray(a: &[i64]) -> i64 {\n    let mut best = a[0];\n    let mut cur = a[0];\n    for &x in &a[1..] {\n        cur = x.max(cur + x);\n        best = best.max(cur);\n    }\n    best\n}\n",
        lua="function max_subarray(a)\n    local best, cur = a[1], a[1]\n    for i = 2, #a do\n        cur = math.max(a[i], cur + a[i])\n        best = math.max(best, cur)\n    end\n    return best\nend\n",
        gdscript="static func max_subarray(a: Array) -> int:\n\tvar best = a[0]\n\tvar cur = a[0]\n\tfor i in range(1, a.size()):\n\t\tcur = max(a[i], cur + a[i])\n\t\tbest = max(best, cur)\n\treturn best\n")

# --- 12 digit_sum ---------------------------------------------------------------------------------------------
problem("digit_sum", [("n", "int")], "int", "algorithms", "The sum of the decimal digits of the non-negative integer `n`.",
        lambda n: sum(int(d) for d in str(n)), [((0,),), ((7,),), ((1234,),), ((99999,),), ((1000001,),), ((405,),)],
        python="def digit_sum(n):\n    s = 0\n    while n > 0:\n        s += n % 10\n        n //= 10\n    return s\n",
        typescript="function digitSum(n: number): number {\n    let s = 0;\n    while (n > 0) {\n        s += n % 10;\n        n = Math.floor(n / 10);\n    }\n    return s;\n}\n",
        cpp="int digitSum(int n) {\n    int s = 0;\n    while (n > 0) {\n        s += n % 10;\n        n /= 10;\n    }\n    return s;\n}\n",
        csharp="public static int DigitSum(int n) {\n    int s = 0;\n    while (n > 0) {\n        s += n % 10;\n        n /= 10;\n    }\n    return s;\n}\n",
        java="public static int digitSum(int n) {\n    int s = 0;\n    while (n > 0) {\n        s += n % 10;\n        n /= 10;\n    }\n    return s;\n}\n",
        go="func DigitSum(n int) int {\n\ts := 0\n\tfor n > 0 {\n\t\ts += n % 10\n\t\tn /= 10\n\t}\n\treturn s\n}\n",
        rust="fn digit_sum(n: i64) -> i64 {\n    let mut n = n;\n    let mut s = 0;\n    while n > 0 {\n        s += n % 10;\n        n /= 10;\n    }\n    s\n}\n",
        lua="function digit_sum(n)\n    local s = 0\n    while n > 0 do\n        s = s + n % 10\n        n = n // 10\n    end\n    return s\nend\n",
        gdscript="static func digit_sum(n: int) -> int:\n\tvar s := 0\n\twhile n > 0:\n\t\ts += n % 10\n\t\tn /= 10\n\treturn s\n")

# --- 13 to_binary ---------------------------------------------------------------------------------------------
problem("to_binary", [("n", "int")], "str", "algorithms", "The binary representation of the non-negative integer `n` as a string (\"0\" for 0, no leading zeros).",
        lambda n: bin(n)[2:], [((0,),), ((1,),), ((2,),), ((5,),), ((255,),), ((1024,),), ((37,),)],
        python="def to_binary(n):\n    if n == 0:\n        return \"0\"\n    out = \"\"\n    while n > 0:\n        out = str(n % 2) + out\n        n //= 2\n    return out\n",
        typescript="function toBinary(n: number): string {\n    if (n === 0) return \"0\";\n    let out = \"\";\n    while (n > 0) {\n        out = (n % 2) + out;\n        n = Math.floor(n / 2);\n    }\n    return out;\n}\n",
        cpp="#include <string>\nstd::string toBinary(int n) {\n    if (n == 0) return \"0\";\n    std::string out;\n    while (n > 0) {\n        out = char('0' + n % 2) + out;\n        n /= 2;\n    }\n    return out;\n}\n",
        csharp="public static string ToBinary(int n) {\n    if (n == 0) return \"0\";\n    string out = \"\";\n    while (n > 0) {\n        out = (n % 2) + out;\n        n /= 2;\n    }\n    return out;\n}\n",
        java="public static String toBinary(int n) {\n    if (n == 0) return \"0\";\n    StringBuilder out = new StringBuilder();\n    while (n > 0) {\n        out.insert(0, n % 2);\n        n /= 2;\n    }\n    return out.toString();\n}\n",
        go="func ToBinary(n int) string {\n\tif n == 0 {\n\t\treturn \"0\"\n\t}\n\tout := \"\"\n\tfor n > 0 {\n\t\tout = string(rune('0'+n%2)) + out\n\t\tn /= 2\n\t}\n\treturn out\n}\n",
        rust="fn to_binary(n: i64) -> String {\n    if n == 0 { return String::from(\"0\"); }\n    let mut n = n;\n    let mut out = String::new();\n    while n > 0 {\n        out.insert(0, if n % 2 == 1 { '1' } else { '0' });\n        n /= 2;\n    }\n    out\n}\n",
        lua="function to_binary(n)\n    if n == 0 then return \"0\" end\n    local out = \"\"\n    while n > 0 do\n        out = tostring(n % 2) .. out\n        n = n // 2\n    end\n    return out\nend\n",
        gdscript="static func to_binary(n: int) -> String:\n\tif n == 0:\n\t\treturn \"0\"\n\tvar out := \"\"\n\twhile n > 0:\n\t\tout = str(n % 2) + out\n\t\tn /= 2\n\treturn out\n")

# --- 14 fizzbuzz ----------------------------------------------------------------------------------------------
def _fizz(n):
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return str(n)


problem("fizzbuzz", [("n", "int")], "str", "basics", "\"FizzBuzz\" when `n` is divisible by 15, \"Fizz\" by 3, \"Buzz\" by 5, otherwise the number as a string.",
        _fizz, [((1,),), ((3,),), ((5,),), ((15,),), ((7,),), ((30,),), ((9,),), ((10,),)],
        python="def fizzbuzz(n):\n    if n % 15 == 0:\n        return \"FizzBuzz\"\n    if n % 3 == 0:\n        return \"Fizz\"\n    if n % 5 == 0:\n        return \"Buzz\"\n    return str(n)\n",
        typescript="function fizzbuzz(n: number): string {\n    if (n % 15 === 0) return \"FizzBuzz\";\n    if (n % 3 === 0) return \"Fizz\";\n    if (n % 5 === 0) return \"Buzz\";\n    return String(n);\n}\n",
        cpp="#include <string>\nstd::string fizzbuzz(int n) {\n    if (n % 15 == 0) return \"FizzBuzz\";\n    if (n % 3 == 0) return \"Fizz\";\n    if (n % 5 == 0) return \"Buzz\";\n    return std::to_string(n);\n}\n",
        csharp="public static string Fizzbuzz(int n) {\n    if (n % 15 == 0) return \"FizzBuzz\";\n    if (n % 3 == 0) return \"Fizz\";\n    if (n % 5 == 0) return \"Buzz\";\n    return n.ToString();\n}\n",
        java="public static String fizzbuzz(int n) {\n    if (n % 15 == 0) return \"FizzBuzz\";\n    if (n % 3 == 0) return \"Fizz\";\n    if (n % 5 == 0) return \"Buzz\";\n    return Integer.toString(n);\n}\n",
        go="import \"strconv\"\n\nfunc Fizzbuzz(n int) string {\n\tif n%15 == 0 {\n\t\treturn \"FizzBuzz\"\n\t}\n\tif n%3 == 0 {\n\t\treturn \"Fizz\"\n\t}\n\tif n%5 == 0 {\n\t\treturn \"Buzz\"\n\t}\n\treturn strconv.Itoa(n)\n}\n",
        rust="fn fizzbuzz(n: i64) -> String {\n    if n % 15 == 0 { String::from(\"FizzBuzz\") }\n    else if n % 3 == 0 { String::from(\"Fizz\") }\n    else if n % 5 == 0 { String::from(\"Buzz\") }\n    else { n.to_string() }\n}\n",
        lua="function fizzbuzz(n)\n    if n % 15 == 0 then return \"FizzBuzz\" end\n    if n % 3 == 0 then return \"Fizz\" end\n    if n % 5 == 0 then return \"Buzz\" end\n    return tostring(n)\nend\n",
        gdscript="static func fizzbuzz(n: int) -> String:\n\tif n % 15 == 0:\n\t\treturn \"FizzBuzz\"\n\tif n % 3 == 0:\n\t\treturn \"Fizz\"\n\tif n % 5 == 0:\n\t\treturn \"Buzz\"\n\treturn str(n)\n")

# --- 15 rotate_left -------------------------------------------------------------------------------------------
problem("rotate_left", [("a", "int[]"), ("k", "int")], "int[]", "data-structures",
        "A new array with the elements of `a` rotated left by `k` positions (k >= 0 may exceed the length; an empty array stays empty).",
        lambda a, k: a[k % len(a):] + a[:k % len(a)] if a else [],
        [(([1, 2, 3, 4, 5], 2),), (([1, 2, 3, 4, 5], 0),), (([1, 2, 3, 4, 5], 5),), (([1, 2, 3, 4, 5], 7),), (([], 3),), (([9], 4),), (([1, 2], 1),)],
        python="def rotate_left(a, k):\n    if not a:\n        return []\n    k %= len(a)\n    return a[k:] + a[:k]\n",
        typescript="function rotateLeft(a: number[], k: number): number[] {\n    if (a.length === 0) return [];\n    k %= a.length;\n    return a.slice(k).concat(a.slice(0, k));\n}\n",
        cpp="#include <vector>\nstd::vector<int> rotateLeft(const std::vector<int>& a, int k) {\n    std::vector<int> out;\n    if (a.empty()) return out;\n    int n = (int)a.size();\n    k %= n;\n    for (int i = 0; i < n; ++i) out.push_back(a[(i + k) % n]);\n    return out;\n}\n",
        csharp="public static int[] RotateLeft(int[] a, int k) {\n    int n = a.Length;\n    int[] out = new int[n];\n    if (n == 0) return out;\n    k %= n;\n    for (int i = 0; i < n; i++) out[i] = a[(i + k) % n];\n    return out;\n}\n",
        java="public static int[] rotateLeft(int[] a, int k) {\n    int n = a.length;\n    int[] out = new int[n];\n    if (n == 0) return out;\n    k %= n;\n    for (int i = 0; i < n; i++) out[i] = a[(i + k) % n];\n    return out;\n}\n",
        go="func RotateLeft(a []int, k int) []int {\n\tn := len(a)\n\tout := make([]int, n)\n\tif n == 0 {\n\t\treturn out\n\t}\n\tk %= n\n\tfor i := 0; i < n; i++ {\n\t\tout[i] = a[(i+k)%n]\n\t}\n\treturn out\n}\n",
        rust="fn rotate_left(a: &[i64], k: i64) -> Vec<i64> {\n    let n = a.len();\n    if n == 0 { return Vec::new(); }\n    let k = (k as usize) % n;\n    (0..n).map(|i| a[(i + k) % n]).collect()\n}\n",
        lua="function rotate_left(a, k)\n    local n = #a\n    local out = {}\n    if n == 0 then return out end\n    k = k % n\n    for i = 1, n do out[i] = a[(i - 1 + k) % n + 1] end\n    return out\nend\n",
        gdscript="static func rotate_left(a: Array, k: int) -> Array:\n\tvar n := a.size()\n\tvar out := []\n\tif n == 0:\n\t\treturn out\n\tk = k % n\n\tfor i in range(n):\n\t\tout.append(a[(i + k) % n])\n\treturn out\n")

# --- 16 unique_sorted -----------------------------------------------------------------------------------------
problem("unique_sorted", [("a", "int[]")], "int[]", "data-structures", "The distinct values of `a` in ascending order.",
        lambda a: sorted(set(a)), [(([3, 1, 2, 3, 1],),), (([],),), (([5, 5, 5],),), (([-1, 0, -1, 7, 3, 0],),), (([10, 9, 8],),)],
        python="def unique_sorted(a):\n    return sorted(set(a))\n",
        typescript="function uniqueSorted(a: number[]): number[] {\n    return Array.from(new Set(a)).sort((x, y) => x - y);\n}\n",
        cpp="#include <vector>\n#include <set>\nstd::vector<int> uniqueSorted(const std::vector<int>& a) {\n    std::set<int> s(a.begin(), a.end());\n    return std::vector<int>(s.begin(), s.end());\n}\n",
        csharp="public static int[] UniqueSorted(int[] a) {\n    return a.Distinct().OrderBy(x => x).ToArray();\n}\n",
        java="public static int[] uniqueSorted(int[] a) {\n    return Arrays.stream(a).distinct().sorted().toArray();\n}\n",
        go="import \"sort\"\n\nfunc UniqueSorted(a []int) []int {\n\tseen := map[int]bool{}\n\tout := []int{}\n\tfor _, x := range a {\n\t\tif !seen[x] {\n\t\t\tseen[x] = true\n\t\t\tout = append(out, x)\n\t\t}\n\t}\n\tsort.Ints(out)\n\treturn out\n}\n",
        rust="fn unique_sorted(a: &[i64]) -> Vec<i64> {\n    let mut v: Vec<i64> = a.to_vec();\n    v.sort();\n    v.dedup();\n    v\n}\n",
        lua="function unique_sorted(a)\n    local seen, out = {}, {}\n    for _, x in ipairs(a) do\n        if not seen[x] then seen[x] = true out[#out + 1] = x end\n    end\n    table.sort(out)\n    return out\nend\n",
        gdscript="static func unique_sorted(a: Array) -> Array:\n\tvar out := []\n\tfor x in a:\n\t\tif not out.has(x):\n\t\t\tout.append(x)\n\tout.sort()\n\treturn out\n")

# --- 17 run_length --------------------------------------------------------------------------------------------
def _rle(s):
    out, i = "", 0
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        out += s[i] + str(j - i)
        i = j
    return out


problem("run_length", [("s", "str")], "str", "strings", "Run-length encoding: each run of equal characters becomes the character followed by its count (\"aaabcc\" -> \"a3b1c2\").",
        _rle, [(("aaabcc",),), (("",),), (("a",),), (("abab",),), (("zzzzzzzzzzzz",),), (("aabbbbccccd",),)],
        python="def run_length(s):\n    out, i = \"\", 0\n    while i < len(s):\n        j = i\n        while j < len(s) and s[j] == s[i]:\n            j += 1\n        out += s[i] + str(j - i)\n        i = j\n    return out\n",
        typescript="function runLength(s: string): string {\n    let out = \"\";\n    let i = 0;\n    while (i < s.length) {\n        let j = i;\n        while (j < s.length && s[j] === s[i]) j++;\n        out += s[i] + (j - i);\n        i = j;\n    }\n    return out;\n}\n",
        cpp="#include <string>\nstd::string runLength(const std::string& s) {\n    std::string out;\n    size_t i = 0;\n    while (i < s.size()) {\n        size_t j = i;\n        while (j < s.size() && s[j] == s[i]) ++j;\n        out += s[i];\n        out += std::to_string(j - i);\n        i = j;\n    }\n    return out;\n}\n",
        csharp="public static string RunLength(string s) {\n    var sb = new System.Text.StringBuilder();\n    int i = 0;\n    while (i < s.Length) {\n        int j = i;\n        while (j < s.Length && s[j] == s[i]) j++;\n        sb.Append(s[i]).Append(j - i);\n        i = j;\n    }\n    return sb.ToString();\n}\n",
        java="public static String runLength(String s) {\n    StringBuilder sb = new StringBuilder();\n    int i = 0;\n    while (i < s.length()) {\n        int j = i;\n        while (j < s.length() && s.charAt(j) == s.charAt(i)) j++;\n        sb.append(s.charAt(i)).append(j - i);\n        i = j;\n    }\n    return sb.toString();\n}\n",
        go="import \"strconv\"\n\nfunc RunLength(s string) string {\n\tout := \"\"\n\ti := 0\n\tfor i < len(s) {\n\t\tj := i\n\t\tfor j < len(s) && s[j] == s[i] {\n\t\t\tj++\n\t\t}\n\t\tout += string(s[i]) + strconv.Itoa(j-i)\n\t\ti = j\n\t}\n\treturn out\n}\n",
        rust="fn run_length(s: &str) -> String {\n    let chars: Vec<char> = s.chars().collect();\n    let mut out = String::new();\n    let mut i = 0;\n    while i < chars.len() {\n        let mut j = i;\n        while j < chars.len() && chars[j] == chars[i] { j += 1; }\n        out.push(chars[i]);\n        out.push_str(&(j - i).to_string());\n        i = j;\n    }\n    out\n}\n",
        lua="function run_length(s)\n    local out, i = \"\", 1\n    while i <= #s do\n        local j = i\n        while j <= #s and s:sub(j, j) == s:sub(i, i) do j = j + 1 end\n        out = out .. s:sub(i, i) .. tostring(j - i)\n        i = j\n    end\n    return out\nend\n",
        gdscript="static func run_length(s: String) -> String:\n\tvar out := \"\"\n\tvar i := 0\n\twhile i < s.length():\n\t\tvar j := i\n\t\twhile j < s.length() and s[j] == s[i]:\n\t\t\tj += 1\n\t\tout += s[i] + str(j - i)\n\t\ti = j\n\treturn out\n")

# --- 18 caesar ------------------------------------------------------------------------------------------------
def _caesar(s, k):
    out = ""
    for c in s:
        if "a" <= c <= "z":
            out += chr((ord(c) - 97 + k) % 26 + 97)
        elif "A" <= c <= "Z":
            out += chr((ord(c) - 65 + k) % 26 + 65)
        else:
            out += c
    return out


problem("caesar", [("s", "str"), ("shift", "int")], "str", "strings", "Caesar cipher: shift every ASCII letter by `shift` (0 <= shift < 26) with wrap-around, keeping case; other characters unchanged.",
        _caesar, [(("abc", 1),), (("xyz", 3),), (("Hello, World!", 13),), (("", 5),), (("STAR ai", 25),), (("abc", 0),)],
        python="def caesar(s, shift):\n    out = \"\"\n    for c in s:\n        if \"a\" <= c <= \"z\":\n            out += chr((ord(c) - 97 + shift) % 26 + 97)\n        elif \"A\" <= c <= \"Z\":\n            out += chr((ord(c) - 65 + shift) % 26 + 65)\n        else:\n            out += c\n    return out\n",
        typescript="function caesar(s: string, shift: number): string {\n    let out = \"\";\n    for (const c of s) {\n        const code = c.charCodeAt(0);\n        if (code >= 97 && code <= 122) out += String.fromCharCode((code - 97 + shift) % 26 + 97);\n        else if (code >= 65 && code <= 90) out += String.fromCharCode((code - 65 + shift) % 26 + 65);\n        else out += c;\n    }\n    return out;\n}\n",
        cpp="#include <string>\nstd::string caesar(const std::string& s, int shift) {\n    std::string out;\n    for (char c : s) {\n        if (c >= 'a' && c <= 'z') out += char((c - 'a' + shift) % 26 + 'a');\n        else if (c >= 'A' && c <= 'Z') out += char((c - 'A' + shift) % 26 + 'A');\n        else out += c;\n    }\n    return out;\n}\n",
        csharp="public static string Caesar(string s, int shift) {\n    var sb = new System.Text.StringBuilder();\n    foreach (char c in s) {\n        if (c >= 'a' && c <= 'z') sb.Append((char)((c - 'a' + shift) % 26 + 'a'));\n        else if (c >= 'A' && c <= 'Z') sb.Append((char)((c - 'A' + shift) % 26 + 'A'));\n        else sb.Append(c);\n    }\n    return sb.ToString();\n}\n",
        java="public static String caesar(String s, int shift) {\n    StringBuilder sb = new StringBuilder();\n    for (char c : s.toCharArray()) {\n        if (c >= 'a' && c <= 'z') sb.append((char) ((c - 'a' + shift) % 26 + 'a'));\n        else if (c >= 'A' && c <= 'Z') sb.append((char) ((c - 'A' + shift) % 26 + 'A'));\n        else sb.append(c);\n    }\n    return sb.toString();\n}\n",
        go="func Caesar(s string, shift int) string {\n\tout := []byte{}\n\tfor i := 0; i < len(s); i++ {\n\t\tc := s[i]\n\t\tif c >= 'a' && c <= 'z' {\n\t\t\tc = byte((int(c-'a')+shift)%26) + 'a'\n\t\t} else if c >= 'A' && c <= 'Z' {\n\t\t\tc = byte((int(c-'A')+shift)%26) + 'A'\n\t\t}\n\t\tout = append(out, c)\n\t}\n\treturn string(out)\n}\n",
        rust="fn caesar(s: &str, shift: i64) -> String {\n    s.chars().map(|c| {\n        if c.is_ascii_lowercase() { (((c as u8 - b'a') as i64 + shift) % 26) as u8 as char + 0 as char; ((((c as u8 - b'a') as i64 + shift) % 26) as u8 + b'a') as char }\n        else if c.is_ascii_uppercase() { ((((c as u8 - b'A') as i64 + shift) % 26) as u8 + b'A') as char }\n        else { c }\n    }).collect()\n}\n",
        lua="function caesar(s, shift)\n    return (s:gsub(\"%a\", function(c)\n        local base = c:match(\"%l\") and 97 or 65\n        return string.char((c:byte() - base + shift) % 26 + base)\n    end))\nend\n",
        gdscript="static func caesar(s: String, shift: int) -> String:\n\tvar out := \"\"\n\tfor c in s:\n\t\tvar code: int = c.unicode_at(0)\n\t\tif code >= 97 and code <= 122:\n\t\t\tout += char((code - 97 + shift) % 26 + 97)\n\t\telif code >= 65 and code <= 90:\n\t\t\tout += char((code - 65 + shift) % 26 + 65)\n\t\telse:\n\t\t\tout += c\n\treturn out\n")

# --- 19 dot ---------------------------------------------------------------------------------------------------
r = _rng("dot")
problem("dot", [("a", "float[]"), ("b", "float[]")], "float", "game-math", "The dot product of two vectors of equal length given as arrays.",
        lambda a, b: sum(x * y for x, y in zip(a, b)),
        [(([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]),), (([0.0, 0.0], [1.0, 1.0]),), (([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),)]
        + [(([r.uniform(-3, 3) for _ in range(3)], [r.uniform(-3, 3) for _ in range(3)]),) for _ in range(3)],
        python="def dot(a, b):\n    return sum(x * y for x, y in zip(a, b))\n",
        typescript="function dot(a: number[], b: number[]): number {\n    let s = 0;\n    for (let i = 0; i < a.length; i++) s += a[i] * b[i];\n    return s;\n}\n",
        cpp="#include <vector>\ndouble dot(const std::vector<double>& a, const std::vector<double>& b) {\n    double s = 0;\n    for (size_t i = 0; i < a.size(); ++i) s += a[i] * b[i];\n    return s;\n}\n",
        csharp="public static double Dot(double[] a, double[] b) {\n    double s = 0;\n    for (int i = 0; i < a.Length; i++) s += a[i] * b[i];\n    return s;\n}\n",
        java="public static double dot(double[] a, double[] b) {\n    double s = 0;\n    for (int i = 0; i < a.length; i++) s += a[i] * b[i];\n    return s;\n}\n",
        go="func Dot(a, b []float64) float64 {\n\ts := 0.0\n\tfor i := range a {\n\t\ts += a[i] * b[i]\n\t}\n\treturn s\n}\n",
        rust="fn dot(a: &[f64], b: &[f64]) -> f64 {\n    a.iter().zip(b.iter()).map(|(x, y)| x * y).sum()\n}\n",
        lua="function dot(a, b)\n    local s = 0\n    for i = 1, #a do s = s + a[i] * b[i] end\n    return s\nend\n",
        gdscript="static func dot(a: Array, b: Array) -> float:\n\tvar s := 0.0\n\tfor i in range(a.size()):\n\t\ts += a[i] * b[i]\n\treturn s\n")

# --- 20 aabb_overlap ------------------------------------------------------------------------------------------
def _aabb(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


problem("aabb_overlap", [("ax", "float"), ("ay", "float"), ("aw", "float"), ("ah", "float"), ("bx", "float"), ("by", "float"), ("bw", "float"), ("bh", "float")],
        "bool", "collision", "True when two axis-aligned rectangles (position of the min corner, width, height) overlap with positive area; touching edges do not count.",
        _aabb, [((0, 0, 2, 2, 1, 1, 2, 2),), ((0, 0, 2, 2, 2, 0, 2, 2),), ((0, 0, 2, 2, 3, 3, 1, 1),), ((0, 0, 10, 10, 2, 2, 1, 1),), ((5, 5, 1, 1, 0, 0, 10, 10),), ((0, 0, 2, 2, -1, -1, 1.5, 1.5),), ((0, 0, 2, 2, 1, 2, 2, 2),)],
        python="def aabb_overlap(ax, ay, aw, ah, bx, by, bw, bh):\n    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah\n",
        typescript="function aabbOverlap(ax: number, ay: number, aw: number, ah: number, bx: number, by: number, bw: number, bh: number): boolean {\n    return ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah;\n}\n",
        cpp="bool aabbOverlap(double ax, double ay, double aw, double ah, double bx, double by, double bw, double bh) {\n    return ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah;\n}\n",
        csharp="public static bool AabbOverlap(double ax, double ay, double aw, double ah, double bx, double by, double bw, double bh) {\n    return ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah;\n}\n",
        java="public static boolean aabbOverlap(double ax, double ay, double aw, double ah, double bx, double by, double bw, double bh) {\n    return ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah;\n}\n",
        go="func AabbOverlap(ax, ay, aw, ah, bx, by, bw, bh float64) bool {\n\treturn ax < bx+bw && bx < ax+aw && ay < by+bh && by < ay+ah\n}\n",
        rust="fn aabb_overlap(ax: f64, ay: f64, aw: f64, ah: f64, bx: f64, by: f64, bw: f64, bh: f64) -> bool {\n    ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah\n}\n",
        lua="function aabb_overlap(ax, ay, aw, ah, bx, by, bw, bh)\n    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah\nend\n",
        gdscript="static func aabb_overlap(ax: float, ay: float, aw: float, ah: float, bx: float, by: float, bw: float, bh: float) -> bool:\n\treturn ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah\n")

# --- 21 balanced_brackets -------------------------------------------------------------------------------------
def _balanced(s):
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for c in s:
        if c in "([{":
            stack.append(c)
        elif c in pairs:
            if not stack or stack.pop() != pairs[c]:
                return False
    return not stack


problem("balanced_brackets", [("s", "str")], "bool", "data-structures", "True when every bracket in `s` ( (), [], {} ) is closed in the right order; other characters are ignored.",
        _balanced, [(("()",),), (("([]{})",),), (("(]",),), (("((",),), (("",),), (("a(b[c]d)e",),), (("}{",),), (("{[()()]}",),), (("([)]",),)],
        python="def balanced_brackets(s):\n    pairs = {\")\": \"(\", \"]\": \"[\", \"}\": \"{\"}\n    stack = []\n    for c in s:\n        if c in \"([{\":\n            stack.append(c)\n        elif c in pairs:\n            if not stack or stack.pop() != pairs[c]:\n                return False\n    return not stack\n",
        typescript="function balancedBrackets(s: string): boolean {\n    const pairs: { [k: string]: string } = { \")\": \"(\", \"]\": \"[\", \"}\": \"{\" };\n    const stack: string[] = [];\n    for (const c of s) {\n        if (\"([{\".includes(c)) stack.push(c);\n        else if (c in pairs) {\n            if (stack.length === 0 || stack.pop() !== pairs[c]) return false;\n        }\n    }\n    return stack.length === 0;\n}\n",
        cpp="#include <string>\n#include <vector>\nbool balancedBrackets(const std::string& s) {\n    std::vector<char> stack;\n    for (char c : s) {\n        if (c == '(' || c == '[' || c == '{') stack.push_back(c);\n        else if (c == ')' || c == ']' || c == '}') {\n            char open = c == ')' ? '(' : c == ']' ? '[' : '{';\n            if (stack.empty() || stack.back() != open) return false;\n            stack.pop_back();\n        }\n    }\n    return stack.empty();\n}\n",
        csharp="public static bool BalancedBrackets(string s) {\n    var stack = new Stack<char>();\n    foreach (char c in s) {\n        if (c == '(' || c == '[' || c == '{') stack.Push(c);\n        else if (c == ')' || c == ']' || c == '}') {\n            char open = c == ')' ? '(' : c == ']' ? '[' : '{';\n            if (stack.Count == 0 || stack.Pop() != open) return false;\n        }\n    }\n    return stack.Count == 0;\n}\n",
        java="public static boolean balancedBrackets(String s) {\n    Deque<Character> stack = new ArrayDeque<>();\n    for (char c : s.toCharArray()) {\n        if (c == '(' || c == '[' || c == '{') stack.push(c);\n        else if (c == ')' || c == ']' || c == '}') {\n            char open = c == ')' ? '(' : c == ']' ? '[' : '{';\n            if (stack.isEmpty() || stack.pop() != open) return false;\n        }\n    }\n    return stack.isEmpty();\n}\n",
        go="func BalancedBrackets(s string) bool {\n\tstack := []byte{}\n\tfor i := 0; i < len(s); i++ {\n\t\tc := s[i]\n\t\tswitch c {\n\t\tcase '(', '[', '{':\n\t\t\tstack = append(stack, c)\n\t\tcase ')', ']', '}':\n\t\t\topen := byte('(')\n\t\t\tif c == ']' {\n\t\t\t\topen = '['\n\t\t\t} else if c == '}' {\n\t\t\t\topen = '{'\n\t\t\t}\n\t\t\tif len(stack) == 0 || stack[len(stack)-1] != open {\n\t\t\t\treturn false\n\t\t\t}\n\t\t\tstack = stack[:len(stack)-1]\n\t\t}\n\t}\n\treturn len(stack) == 0\n}\n",
        rust="fn balanced_brackets(s: &str) -> bool {\n    let mut stack: Vec<char> = Vec::new();\n    for c in s.chars() {\n        match c {\n            '(' | '[' | '{' => stack.push(c),\n            ')' | ']' | '}' => {\n                let open = match c { ')' => '(', ']' => '[', _ => '{' };\n                if stack.pop() != Some(open) { return false; }\n            }\n            _ => {}\n        }\n    }\n    stack.is_empty()\n}\n",
        lua="function balanced_brackets(s)\n    local pairs_ = { [\")\"] = \"(\", [\"]\"] = \"[\", [\"}\"] = \"{\" }\n    local stack = {}\n    for c in s:gmatch(\".\") do\n        if c == \"(\" or c == \"[\" or c == \"{\" then\n            stack[#stack + 1] = c\n        elseif pairs_[c] then\n            if #stack == 0 or table.remove(stack) ~= pairs_[c] then return false end\n        end\n    end\n    return #stack == 0\nend\n",
        gdscript="static func balanced_brackets(s: String) -> bool:\n\tvar pairs := {\")\": \"(\", \"]\": \"[\", \"}\": \"{\"}\n\tvar stack := []\n\tfor c in s:\n\t\tif c in \"([{\":\n\t\t\tstack.append(c)\n\t\telif c in pairs:\n\t\t\tif stack.is_empty() or stack.pop_back() != pairs[c]:\n\t\t\t\treturn false\n\treturn stack.is_empty()\n")

# --- 22 damage_after_armor ------------------------------------------------------------------------------------
problem("damage_after_armor", [("damage", "float"), ("armor", "float")], "float", "game-design",
        "Damage after armor with the common formula damage * 100 / (100 + armor); armor below 0 counts as 0.",
        lambda d, a: d * 100.0 / (100.0 + max(0.0, a)),
        [((100.0, 0.0),), ((100.0, 100.0),), ((50.0, 25.0),), ((80.0, -30.0),), ((0.0, 50.0),), ((37.5, 300.0),)],
        python="def damage_after_armor(damage, armor):\n    armor = max(0.0, armor)\n    return damage * 100.0 / (100.0 + armor)\n",
        typescript="function damageAfterArmor(damage: number, armor: number): number {\n    armor = Math.max(0, armor);\n    return damage * 100 / (100 + armor);\n}\n",
        cpp="double damageAfterArmor(double damage, double armor) {\n    if (armor < 0) armor = 0;\n    return damage * 100.0 / (100.0 + armor);\n}\n",
        csharp="public static double DamageAfterArmor(double damage, double armor) {\n    armor = Math.Max(0, armor);\n    return damage * 100.0 / (100.0 + armor);\n}\n",
        java="public static double damageAfterArmor(double damage, double armor) {\n    armor = Math.max(0, armor);\n    return damage * 100.0 / (100.0 + armor);\n}\n",
        go="func DamageAfterArmor(damage, armor float64) float64 {\n\tif armor < 0 {\n\t\tarmor = 0\n\t}\n\treturn damage * 100.0 / (100.0 + armor)\n}\n",
        rust="fn damage_after_armor(damage: f64, armor: f64) -> f64 {\n    let armor = armor.max(0.0);\n    damage * 100.0 / (100.0 + armor)\n}\n",
        lua="function damage_after_armor(damage, armor)\n    armor = math.max(0, armor)\n    return damage * 100 / (100 + armor)\nend\n",
        gdscript="static func damage_after_armor(damage: float, armor: float) -> float:\n\tarmor = maxf(0.0, armor)\n\treturn damage * 100.0 / (100.0 + armor)\n")

# --- 23 wrap_angle --------------------------------------------------------------------------------------------
def _wrap(deg):
    a = (deg + 180.0) % 360.0 - 180.0
    return a if a != -180.0 else 180.0


problem("wrap_angle", [("deg", "float")], "float", "game-math", "Wrap an angle in degrees into the range (-180, 180].",
        _wrap, [((0.0,),), ((190.0,),), ((-190.0,),), ((360.0,),), ((540.0,),), ((180.0,),), ((-180.0,),), ((725.5,),)],
        python="def wrap_angle(deg):\n    a = (deg + 180.0) % 360.0 - 180.0\n    return 180.0 if a == -180.0 else a\n",
        typescript="function wrapAngle(deg: number): number {\n    let a = ((deg + 180) % 360 + 360) % 360 - 180;\n    return a === -180 ? 180 : a;\n}\n",
        cpp="#include <cmath>\ndouble wrapAngle(double deg) {\n    double a = std::fmod(deg + 180.0, 360.0);\n    if (a < 0) a += 360.0;\n    a -= 180.0;\n    return a == -180.0 ? 180.0 : a;\n}\n",
        csharp="public static double WrapAngle(double deg) {\n    double a = (deg + 180.0) % 360.0;\n    if (a < 0) a += 360.0;\n    a -= 180.0;\n    return a == -180.0 ? 180.0 : a;\n}\n",
        java="public static double wrapAngle(double deg) {\n    double a = (deg + 180.0) % 360.0;\n    if (a < 0) a += 360.0;\n    a -= 180.0;\n    return a == -180.0 ? 180.0 : a;\n}\n",
        go="import \"math\"\n\nfunc WrapAngle(deg float64) float64 {\n\ta := math.Mod(deg+180.0, 360.0)\n\tif a < 0 {\n\t\ta += 360.0\n\t}\n\ta -= 180.0\n\tif a == -180.0 {\n\t\treturn 180.0\n\t}\n\treturn a\n}\n",
        rust="fn wrap_angle(deg: f64) -> f64 {\n    let a = (deg + 180.0).rem_euclid(360.0) - 180.0;\n    if a == -180.0 { 180.0 } else { a }\n}\n",
        lua="function wrap_angle(deg)\n    local a = (deg + 180) % 360 - 180\n    if a == -180 then return 180 end\n    return a\nend\n",
        gdscript="static func wrap_angle(deg: float) -> float:\n\tvar a := fposmod(deg + 180.0, 360.0) - 180.0\n\treturn 180.0 if a == -180.0 else a\n")

# --- 24 moving_average ----------------------------------------------------------------------------------------
def _mavg(a, k):
    return [sum(a[i:i + k]) / k for i in range(len(a) - k + 1)] if k <= len(a) else []


problem("moving_average", [("a", "float[]"), ("k", "int")], "float[]", "game-math",
        "The moving averages of `a` over windows of `k` consecutive values (k >= 1); empty when `k` exceeds the length.",
        _mavg, [(([1.0, 2.0, 3.0, 4.0, 5.0], 2),), (([1.0, 2.0, 3.0, 4.0, 5.0], 5),), (([1.0, 2.0], 3),), (([4.0, 8.0, 6.0, 2.0], 1),), (([3.0, 1.0, 4.0, 1.0, 5.0, 9.0], 3),)],
        python="def moving_average(a, k):\n    return [sum(a[i:i + k]) / k for i in range(len(a) - k + 1)]\n",
        typescript="function movingAverage(a: number[], k: number): number[] {\n    const out: number[] = [];\n    for (let i = 0; i + k <= a.length; i++) {\n        let s = 0;\n        for (let j = i; j < i + k; j++) s += a[j];\n        out.push(s / k);\n    }\n    return out;\n}\n",
        cpp="#include <vector>\nstd::vector<double> movingAverage(const std::vector<double>& a, int k) {\n    std::vector<double> out;\n    for (size_t i = 0; i + k <= a.size(); ++i) {\n        double s = 0;\n        for (size_t j = i; j < i + k; ++j) s += a[j];\n        out.push_back(s / k);\n    }\n    return out;\n}\n",
        csharp="public static double[] MovingAverage(double[] a, int k) {\n    var out = new List<double>();\n    for (int i = 0; i + k <= a.Length; i++) {\n        double s = 0;\n        for (int j = i; j < i + k; j++) s += a[j];\n        out.Add(s / k);\n    }\n    return out.ToArray();\n}\n",
        java="public static double[] movingAverage(double[] a, int k) {\n    int n = Math.max(0, a.length - k + 1);\n    double[] out = new double[n];\n    for (int i = 0; i < n; i++) {\n        double s = 0;\n        for (int j = i; j < i + k; j++) s += a[j];\n        out[i] = s / k;\n    }\n    return out;\n}\n",
        go="func MovingAverage(a []float64, k int) []float64 {\n\tout := []float64{}\n\tfor i := 0; i+k <= len(a); i++ {\n\t\ts := 0.0\n\t\tfor j := i; j < i+k; j++ {\n\t\t\ts += a[j]\n\t\t}\n\t\tout = append(out, s/float64(k))\n\t}\n\treturn out\n}\n",
        rust="fn moving_average(a: &[f64], k: i64) -> Vec<f64> {\n    let k = k as usize;\n    if k == 0 || k > a.len() { return Vec::new(); }\n    a.windows(k).map(|w| w.iter().sum::<f64>() / k as f64).collect()\n}\n",
        lua="function moving_average(a, k)\n    local out = {}\n    for i = 1, #a - k + 1 do\n        local s = 0\n        for j = i, i + k - 1 do s = s + a[j] end\n        out[#out + 1] = s / k\n    end\n    return out\nend\n",
        gdscript="static func moving_average(a: Array, k: int) -> Array:\n\tvar out := []\n\tfor i in range(a.size() - k + 1):\n\t\tvar s := 0.0\n\t\tfor j in range(i, i + k):\n\t\t\ts += a[j]\n\t\tout.append(s / k)\n\treturn out\n")

# --- 25 xp_for_level ------------------------------------------------------------------------------------------
problem("xp_for_level", [("level", "int")], "int", "game-design",
        "Total experience needed to reach `level` (level >= 1) when each level-up from L to L+1 costs 100 * L: xp(1) = 0, xp(2) = 100, xp(3) = 300.",
        lambda L: 100 * L * (L - 1) // 2, [((1,),), ((2,),), ((3,),), ((10,),), ((50,),), ((7,),)],
        python="def xp_for_level(level):\n    return 100 * level * (level - 1) // 2\n",
        typescript="function xpForLevel(level: number): number {\n    return 100 * level * (level - 1) / 2;\n}\n",
        cpp="int xpForLevel(int level) {\n    return 100 * level * (level - 1) / 2;\n}\n",
        csharp="public static int XpForLevel(int level) {\n    return 100 * level * (level - 1) / 2;\n}\n",
        java="public static int xpForLevel(int level) {\n    return 100 * level * (level - 1) / 2;\n}\n",
        go="func XpForLevel(level int) int {\n\treturn 100 * level * (level - 1) / 2\n}\n",
        rust="fn xp_for_level(level: i64) -> i64 {\n    100 * level * (level - 1) / 2\n}\n",
        lua="function xp_for_level(level)\n    return 100 * level * (level - 1) // 2\nend\n",
        gdscript="static func xp_for_level(level: int) -> int:\n\treturn 100 * level * (level - 1) / 2\n")

# --- 26 word_count --------------------------------------------------------------------------------------------
problem("word_count", [("s", "str")], "int", "strings", "The number of words in `s`, where words are separated by one or more spaces (0 for an empty or all-space string).",
        lambda s: len(s.split()), [(("hello world",),), (("",),), (("   ",),), (("one",),), (("  a  b   c ",),), (("the quick brown fox",),)],
        python="def word_count(s):\n    return len(s.split())\n",
        typescript="function wordCount(s: string): number {\n    const t = s.trim();\n    return t === \"\" ? 0 : t.split(/\\s+/).length;\n}\n",
        cpp="#include <string>\nint wordCount(const std::string& s) {\n    int n = 0;\n    bool inWord = false;\n    for (char c : s) {\n        if (c == ' ') inWord = false;\n        else if (!inWord) { inWord = true; ++n; }\n    }\n    return n;\n}\n",
        csharp="public static int WordCount(string s) {\n    return s.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length;\n}\n",
        java="public static int wordCount(String s) {\n    String t = s.trim();\n    return t.isEmpty() ? 0 : t.split(\"\\\\s+\").length;\n}\n",
        go="import \"strings\"\n\nfunc WordCount(s string) int {\n\treturn len(strings.Fields(s))\n}\n",
        rust="fn word_count(s: &str) -> i64 {\n    s.split_whitespace().count() as i64\n}\n",
        lua="function word_count(s)\n    local n = 0\n    for _ in s:gmatch(\"%S+\") do n = n + 1 end\n    return n\nend\n",
        gdscript="static func word_count(s: String) -> int:\n\tvar n := 0\n\tfor w in s.split(\" \"):\n\t\tif w != \"\":\n\t\t\tn += 1\n\treturn n\n")

# Rust reference of caesar above has a stray expression; keep it clean.
for _p in PROBLEMS:
    if _p["fn"] == "caesar":
        _p["refs"]["rust"] = ("fn caesar(s: &str, shift: i64) -> String {\n    s.chars().map(|c| {\n        if c.is_ascii_lowercase() { ((((c as u8 - b'a') as i64 + shift) % 26) as u8 + b'a') as char }\n"
                              "        else if c.is_ascii_uppercase() { ((((c as u8 - b'A') as i64 + shift) % 26) as u8 + b'A') as char }\n        else { c }\n    }).collect()\n}\n")


def cases_of(p: dict) -> list:
    """[(args, expected)] from the oracle."""
    out = []
    for (args,) in p["cases"]:
        want = p["oracle"](*[list(a) if isinstance(a, list) else a for a in args])
        out.append((args, want))
    return out
