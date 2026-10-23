// llama-score: prefill-only scoring for Star Oracle (star/oracle). No generation, no sampling.
//
// Reads JSONL items {"id": str, "prefix": str, "targets": [str, ...]} (text already in the model's chat template;
// special tokens are parsed) and writes one JSONL row per item:
//   {"id", "n_prefix", "targets": [{"n", "sum_logprob", "top1_hits", ["topk"], ["kl_sum", "agree"]}]}
// sum_logprob is the log-probability of the target tokens given the prefix; top1_hits counts target tokens that were
// the model's argmax. With --topk K the K most likely tokens per position of each item's FIRST target are written
// (a reference file for L1). With --ref FILE (an earlier --topk output for the same items) each position also
// gets the KL divergence
// KL(ref || this) over the reference's top-K tokens plus one "rest" bucket, and whether both argmaxes agree
// (targets without a reference top-K get no KL).
//
// Build: server/oracle/build_score.sh (Linux, against a llama.cpp tree) or build_score_win.py (zig, against a
// release's DLLs plus the matching source headers).
#include "llama.h"
#include "ggml-backend.h"
#include "nlohmann/json.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

using json = nlohmann::json;

struct Args {
    std::string model, in, out, ref;
    std::vector<std::string> loras;
    int ngl = 0, n_ctx = 8192, n_batch = 512, threads = 0, topk = 0;
};

static void usage() {
    fprintf(stderr, "usage: llama-score -m MODEL --in ITEMS.jsonl --out OUT.jsonl [--lora F]... [-ngl N] [-c CTX] "
                    "[-b BATCH] [-t THREADS] [--topk K] [--ref REF.jsonl]\n");
}

static bool parse(int argc, char ** argv, Args & a) {
    for (int i = 1; i < argc; i++) {
        std::string k = argv[i];
        auto next = [&](void) -> const char * { return i + 1 < argc ? argv[++i] : nullptr; };
        const char * v = nullptr;
        if (k == "-m") { if (!(v = next())) return false; a.model = v; }
        else if (k == "--in") { if (!(v = next())) return false; a.in = v; }
        else if (k == "--out") { if (!(v = next())) return false; a.out = v; }
        else if (k == "--ref") { if (!(v = next())) return false; a.ref = v; }
        else if (k == "--lora") { if (!(v = next())) return false; a.loras.push_back(v); }
        else if (k == "-ngl") { if (!(v = next())) return false; a.ngl = atoi(v); }
        else if (k == "-c") { if (!(v = next())) return false; a.n_ctx = atoi(v); }
        else if (k == "-b") { if (!(v = next())) return false; a.n_batch = atoi(v); }
        else if (k == "-t") { if (!(v = next())) return false; a.threads = atoi(v); }
        else if (k == "--topk") { if (!(v = next())) return false; a.topk = atoi(v); }
        else return false;
    }
    return !a.model.empty() && !a.in.empty() && !a.out.empty() && a.n_batch > 0 && a.n_ctx > 0;
}

static std::vector<llama_token> tokenize(const llama_vocab * vocab, const std::string & text, bool add_special) {
    int n = -llama_tokenize(vocab, text.data(), (int32_t) text.size(), nullptr, 0, add_special, true);
    std::vector<llama_token> out(std::max(n, 0));
    if (n > 0) {
        llama_tokenize(vocab, text.data(), (int32_t) text.size(), out.data(), n, add_special, true);
    }
    return out;
}

// Decode tokens at positions [pos0, pos0 + n) of sequence 0 in chunks of n_batch. With all_logits, on_chunk(start,
// rows) gets the logits of every position of the chunk right after it is decoded (rows[j] = position start + j);
// the last position's logits are always copied into last. Returns false on a decode error.
template <typename F>
static bool decode(llama_context * ctx, llama_batch & batch, const std::vector<llama_token> & toks, int pos0,
                   int n_batch, int n_vocab, bool all_logits, std::vector<float> & last, F on_chunk) {
    std::vector<const float *> rows;
    for (size_t start = 0; start < toks.size(); start += n_batch) {
        size_t end = std::min(toks.size(), start + (size_t) n_batch);
        batch.n_tokens = 0;
        for (size_t i = start; i < end; i++) {
            int j = batch.n_tokens++;
            batch.token[j] = toks[i];
            batch.pos[j] = pos0 + (int) i;
            batch.n_seq_id[j] = 1;
            batch.seq_id[j][0] = 0;
            batch.logits[j] = all_logits || i + 1 == toks.size();
        }
        if (llama_decode(ctx, batch) != 0) {
            return false;
        }
        rows.clear();
        for (int j = 0; j < batch.n_tokens; j++) {
            if (batch.logits[j]) rows.push_back(llama_get_logits_ith(ctx, j));
        }
        if (all_logits) on_chunk(start, rows);
        if (end == toks.size()) last.assign(rows.back(), rows.back() + n_vocab);
    }
    return true;
}

// What one target position contributes; computed independently per position (in parallel).
struct PosStat {
    double lp = 0, kl = 0;
    int arg = 0, agree = 0;
    std::vector<std::pair<int, float>> top;
};

static void score_position(const float * l, int n_vocab, llama_token tok, int topk, const json * rp, PosStat & st) {
    float mx = l[0];
    int arg = 0;
    for (int v = 1; v < n_vocab; v++) {
        if (l[v] > mx) { mx = l[v]; arg = v; }
    }
    double s = 0;
    for (int v = 0; v < n_vocab; v++) s += std::exp((double) (l[v] - mx));
    double lse = mx + std::log(s);
    st.lp = l[tok] - lse;
    st.arg = arg;
    if (topk > 0) {
        // the K largest logits: a small min-heap over the vocabulary
        auto cmp = [](const std::pair<int, float> & x, const std::pair<int, float> & y) { return x.second > y.second; };
        std::vector<std::pair<int, float>> heap;
        heap.reserve(topk + 1);
        for (int v = 0; v < n_vocab; v++) {
            if ((int) heap.size() < topk) {
                heap.push_back({v, l[v]});
                std::push_heap(heap.begin(), heap.end(), cmp);
            } else if (l[v] > heap.front().second) {
                std::pop_heap(heap.begin(), heap.end(), cmp);
                heap.back() = {v, l[v]};
                std::push_heap(heap.begin(), heap.end(), cmp);
            }
        }
        std::sort(heap.begin(), heap.end(), [](auto & x, auto & y) { return x.second > y.second; });
        for (auto & e : heap) e.second = (float) (e.second - lse);
        st.top = std::move(heap);
    }
    if (rp) {
        double p_rest = 1, q_rest = 1, kl = 0;
        for (auto & e : *rp) {
            int id = e[0].get<int>();
            double lp_ref = e[1].get<double>(), lq = l[id] - lse;
            double p = std::exp(lp_ref);
            kl += p * (lp_ref - lq);
            p_rest -= p;
            q_rest -= std::exp(lq);
        }
        if (p_rest > 1e-12) kl += p_rest * std::log(p_rest / std::max(q_rest, 1e-12));
        st.kl = std::max(kl, 0.0);
        st.agree = (*rp)[0][0].get<int>() == arg;
    }
}

template <typename F>
static void parallel_for(size_t n, int threads, F fn) {
    if (threads <= 1 || n < 2) {
        for (size_t i = 0; i < n; i++) fn(i);
        return;
    }
    std::vector<std::thread> pool;
    for (int t = 0; t < threads; t++) {
        pool.emplace_back([&, t] { for (size_t i = t; i < n; i += threads) fn(i); });
    }
    for (auto & th : pool) th.join();
}

int main(int argc, char ** argv) {
    Args a;
    if (!parse(argc, argv, a)) { usage(); return 2; }
    std::vector<json> refs;
    if (!a.ref.empty()) {
        std::ifstream rf(a.ref);
        std::string line;
        while (std::getline(rf, line)) if (!line.empty()) refs.push_back(json::parse(line));
    }

    ggml_backend_load_all();
    llama_backend_init();
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = a.ngl;
    llama_model * model = llama_model_load_from_file(a.model.c_str(), mp);
    if (!model) { fprintf(stderr, "cannot load model %s\n", a.model.c_str()); return 1; }
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = a.n_ctx;
    cp.n_batch = a.n_batch;
    cp.n_ubatch = a.n_batch;
    cp.n_seq_max = 1;
    if (a.threads > 0) { cp.n_threads = a.threads; cp.n_threads_batch = a.threads; }
    llama_context * ctx = llama_init_from_model(model, cp);
    if (!ctx) { fprintf(stderr, "cannot create context\n"); return 1; }
    std::vector<llama_adapter_lora *> adapters;
    std::vector<float> scales;
    for (auto & path : a.loras) {
        llama_adapter_lora * ad = llama_adapter_lora_init(model, path.c_str());
        if (!ad) { fprintf(stderr, "cannot load lora %s\n", path.c_str()); return 1; }
        adapters.push_back(ad);
        scales.push_back(1.0f);
    }
    if (!adapters.empty() && llama_set_adapters_lora(ctx, adapters.data(), adapters.size(), scales.data()) != 0) {
        fprintf(stderr, "cannot apply lora\n"); return 1;
    }

    const llama_vocab * vocab = llama_model_get_vocab(model);
    const int n_vocab = llama_vocab_n_tokens(vocab);
    llama_memory_t mem = llama_get_memory(ctx);
    llama_batch batch = llama_batch_init(a.n_batch, 0, 1);
    std::ifstream in(a.in);
    std::ofstream out(a.out);
    if (!in || !out) { fprintf(stderr, "cannot open --in or --out\n"); return 1; }
    std::string line;
    size_t row = 0;
    std::vector<float> prefix_last, scratch;
    const int work_threads = a.threads > 0 ? a.threads : std::max(1, (int) std::thread::hardware_concurrency() / 2);
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        json item = json::parse(line);
        json res = {{"id", item.value("id", std::to_string(row))}};
        const json * ref = nullptr;
        if (!refs.empty()) {
            if (row >= refs.size() || refs[row].value("id", std::string()) != res["id"].get<std::string>()) {
                fprintf(stderr, "reference row %zu does not match item %s\n", row, res["id"].dump().c_str());
                return 1;
            }
            ref = &refs[row];
        }
        row++;
        std::vector<llama_token> prefix = tokenize(vocab, item.value("prefix", std::string()),
                                                   llama_vocab_get_add_bos(vocab));
        res["n_prefix"] = prefix.size();
        json targets = json::array();
        bool prefix_ready = false;
        size_t ti = 0;
        for (auto & tj : item["targets"]) {
            json t;
            std::vector<llama_token> toks = tokenize(vocab, tj.get<std::string>(), false);
            if (toks.empty() || prefix.empty() || prefix.size() + toks.size() > (size_t) a.n_ctx) {
                t["error"] = toks.empty() ? "empty target" : "too long";
                targets.push_back(t); ti++;
                continue;
            }
            const json * rt = nullptr;
            if (ref && ti < (*ref)["targets"].size() && (*ref)["targets"][ti].contains("topk")) {
                rt = &(*ref)["targets"][ti];
                if ((*rt)["topk"].size() != toks.size()) {
                    fprintf(stderr, "reference for %s target %zu has no matching topk\n", res["id"].dump().c_str(), ti);
                    return 1;
                }
            }
            // Reuse the prefix in the cache when the memory allows a partial removal (not every architecture does).
            if (!prefix_ready || !llama_memory_seq_rm(mem, 0, (llama_pos) prefix.size(), -1)) {
                llama_memory_clear(mem, true);
                prefix_ready = decode(ctx, batch, prefix, 0, a.n_batch, n_vocab, false, prefix_last,
                                      [](size_t, const std::vector<const float *> &) {});
                if (!prefix_ready) {
                    t["error"] = "decode failed"; targets.push_back(t); ti++;
                    continue;
                }
            }
            std::vector<PosStat> stats(toks.size());
            const int topk = ti == 0 ? a.topk : 0;
            auto ref_pos = [&](size_t i) -> const json * { return rt ? &(*rt)["topk"][i] : nullptr; };
            // position i is predicted by the previous row: the prefix's last row for i = 0, then target rows.
            score_position(prefix_last.data(), n_vocab, toks[0], topk, ref_pos(0), stats[0]);
            bool ok = decode(ctx, batch, toks, (int) prefix.size(), a.n_batch, n_vocab, true, scratch,
                             [&](size_t start, const std::vector<const float *> & rows) {
                parallel_for(rows.size(), work_threads, [&](size_t j) {
                    size_t i = start + j + 1;
                    if (i < toks.size()) score_position(rows[j], n_vocab, toks[i], topk, ref_pos(i), stats[i]);
                });
            });
            if (!ok) {
                t["error"] = "decode failed"; targets.push_back(t); ti++; prefix_ready = false;
                continue;
            }
            double sum = 0, kl_sum = 0;
            int hits = 0, agree = 0;
            json topk_rows = json::array();
            for (size_t i = 0; i < toks.size(); i++) {
                sum += stats[i].lp;
                hits += stats[i].arg == toks[i];
                kl_sum += stats[i].kl;
                agree += stats[i].agree;
                if (topk) {
                    json pos = json::array();
                    for (auto & e : stats[i].top) pos.push_back({e.first, e.second});
                    topk_rows.push_back(pos);
                }
            }
            t["n"] = toks.size();
            t["sum_logprob"] = sum;
            t["top1_hits"] = hits;
            if (topk) t["topk"] = topk_rows;
            if (rt) { t["kl_sum"] = kl_sum; t["agree"] = agree; }
            targets.push_back(t);
            ti++;
        }
        res["targets"] = targets;
        out << res.dump() << "\n";
        out.flush();
    }
    llama_batch_free(batch);
    llama_free(ctx);
    llama_model_free(model);
    llama_backend_free();
    return 0;
}
