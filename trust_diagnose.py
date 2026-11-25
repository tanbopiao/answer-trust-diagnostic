#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Answer Trust Diagnostic — read-only audit of an AI assistant's answer
verifiability.

Checks whether the assistant's answers can be verified by the people who
receive them: citation instructions in system prompts, source metadata
passed with retrieved context, citation markers in rendered answers,
abstention/fallback behaviour when retrieval comes up empty.

Read-only. The report contains NO secret values and NO file contents —
only filenames, counts, booleans and recommendations.

Usage:
    python trust_diagnose.py [project_dir] [--output DIR] [--compare OLD.json] [--json]
"""
import argparse
import datetime
import json
import os
import platform
import re
import sys

TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = 2

SEV_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}

SELF_FIX_HOURS = {
    "TRUST-NO-CITATION-PROMPT": 1,     # add citation requirement to system prompt
    "TRUST-SOURCE-NOT-PASSED": 3,      # thread source metadata through retrieval
    "TRUST-NO-ABSTAIN": 2,             # add abstention/confidence policy
    "TRUST-EMPTY-RETRIEVAL-FALLBACK": 2,
    "TRUST-CITATION-OK": 0,
    "TRUST-RETRIEVAL-OK": 0,
    "TRUST-NO-RETRIEVAL": 0,
}


def fix_hours(fid):
    base = fid.split(":", 1)[0]
    return SELF_FIX_HOURS.get(base, 0)


def finding(fid, severity, title, detail="", advice=""):
    return {"id": fid, "severity": severity, "title": title,
            "detail": detail, "advice": advice, "self_fix_hours": fix_hours(fid)}


def safe_read(path, limit=200_000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except Exception:
        return ""


def walk_files(root, depth=3, max_files=3000):
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv",
            "site-packages", "dist-info", ".cache", "data", "logs"}
    count = 0
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        if dirpath.rstrip(os.sep).count(os.sep) - root_depth >= depth:
            dirnames[:] = []
        for name in filenames:
            yield os.path.join(dirpath, name)
            count += 1
            if count >= max_files:
                return


CITATION_PROMPT_RE = re.compile(
    r"(cite|citation|cite the source|according to the (document|source)|"
    r"引用来源|注明出处|根据.{0,6}(文档|资料|来源)回答)", re.IGNORECASE)
SOURCE_META_RE = re.compile(
    r"(\"?(?:source|doc_id|document|filename|file_name|section|page|version|"
    r"metadata)\"?\s*[:=])", re.IGNORECASE)
RETRIEVAL_RE = re.compile(
    r"(retriev|search\(|vector|embedding|top_k|similarity|bm25|"
    r"知识库|检索)", re.IGNORECASE)
ABSTAIN_RE = re.compile(
    r"(I don't know|not (?:enough|sufficient) (?:information|context)|"
    r"无法回答|信息不足|不知道|abstain|refuse to answer|out of scope)", re.IGNORECASE)
CONFIDENCE_RE = re.compile(
    r"(confidence|score|threshold|置信度|阈值)", re.IGNORECASE)


def is_code(name):
    return name.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go"))


def is_prompt_like(relpath, base):
    b = base.lower()
    return b.startswith(("prompt", "system_prompt")) or "prompt" in b


def gather(project_dir):
    findings = []
    facts = {"generated_at": datetime.datetime.now().isoformat(),
             "project_dir": os.path.abspath(project_dir)}

    prompt_files, code_files = [], []
    for fp in walk_files(project_dir):
        rel = os.path.relpath(fp, project_dir)
        base = os.path.basename(fp)
        if is_prompt_like(rel, base) and base.endswith(
                (".txt", ".md", ".py", ".js", ".ts", ".yaml", ".yml", ".json")):
            prompt_files.append((fp, rel))
        elif is_code(base):
            code_files.append((fp, rel))

    facts["prompt_like_files"] = [rel for _, rel in prompt_files[:20]]
    facts["code_files_scanned"] = len(code_files)

    # 1. Citation requirement in system prompts
    has_citation_prompt = False
    for fp, rel in prompt_files:
        text = safe_read(fp)
        if text and CITATION_PROMPT_RE.search(text):
            has_citation_prompt = True
            break
    facts["citation_instruction_found"] = has_citation_prompt
    if prompt_files and not has_citation_prompt:
        findings.append(finding(
            "TRUST-NO-CITATION-PROMPT", "high",
            "System prompt does not require answers to cite their sources",
            "Scanned %d prompt-like file(s); none asks the model to cite the "
            "document/section an answer comes from." % len(prompt_files),
            "Add a citation requirement to the system prompt: every answer "
            "must name the source document and section, so operators can "
            "verify before acting."))
    elif not prompt_files:
        findings.append(finding(
            "TRUST-NO-CITATION-PROMPT", "high",
            "No system prompt file found in the scanned directory",
            "Prompt-like files (prompt*, system_prompt*) were not found here.",
            "Locate where the assistant's instructions live and require "
            "source citations for every answer; then re-run this tool there."))

    # 2. Retrieval pipeline: is source metadata passed along?
    retrieval_files = []
    for fp, rel in code_files:
        text = safe_read(fp, 100_000)
        if text and RETRIEVAL_RE.search(text):
            retrieval_files.append((fp, rel, text))
    facts["retrieval_code_files"] = [rel for _, rel, _ in retrieval_files[:20]]

    if retrieval_files:
        with_meta = [rel for _, rel, t in retrieval_files
                     if SOURCE_META_RE.search(t)]
        facts["retrieval_files_with_source_meta"] = len(with_meta)
        if not with_meta:
            findings.append(finding(
                "TRUST-SOURCE-NOT-PASSED", "high",
                "Retrieval code does not appear to pass source metadata with the context",
                "Found %d file(s) with retrieval logic; none references "
                "source/document/section metadata alongside the retrieved text." % len(retrieval_files),
                "Thread the source (document name, section, version) through "
                "the retrieval pipeline so the model can cite it and the "
                "operator can verify it."))
        else:
            findings.append(finding(
                "TRUST-RETRIEVAL-OK", "info",
                "Source metadata is passed with retrieved context",
                "%d of %d retrieval file(s) reference source metadata."
                % (len(with_meta), len(retrieval_files)),
                "Make sure the citation actually reaches the final answer, "
                "not just the model context."))
    else:
        findings.append(finding(
            "TRUST-NO-RETRIEVAL", "info",
            "No retrieval/RAG pipeline detected in the scanned directory",
            "No retrieval, vector-search or knowledge-base code found.",
            "If the assistant answers from a knowledge base, run this tool "
            "where the retrieval service lives."))

    # 3. Abstention / empty-retrieval fallback
    all_code_text = "\n".join(t for _, _, t in retrieval_files)
    has_abstain = bool(ABSTAIN_RE.search(all_code_text)) or any(
        ABSTAIN_RE.search(safe_read(fp, 100_000)) for fp, _ in prompt_files)
    has_confidence = bool(CONFIDENCE_RE.search(all_code_text))
    facts["abstention_hint"] = has_abstain
    facts["confidence_hint"] = has_confidence
    if retrieval_files and not has_abstain:
        findings.append(finding(
            "TRUST-NO-ABSTAIN", "medium",
            "No abstention policy detected when the answer is not in the knowledge base",
            "No 'I don't know' / insufficient-information handling found in "
            "retrieval or prompt code.",
            "Define what the assistant must say when retrieval finds nothing: "
            "an explicit 'not in the knowledge base' beats a confident guess."))
    if retrieval_files and not has_confidence:
        findings.append(finding(
            "TRUST-EMPTY-RETRIEVAL-FALLBACK", "medium",
            "No confidence/score threshold before answering",
            "Retrieval scores exist but nothing checks them against a "
            "threshold before the model answers.",
            "Gate the answer on a minimum retrieval score; below it, the "
            "assistant should ask for clarification or escalate to a human."))

    findings.sort(key=lambda f: (SEV_RANK[f["severity"]], f["id"]))
    summary = {s: sum(1 for f in findings if f["severity"] == s)
               for s in ("high", "medium", "low", "info")}
    return {
        "report_type": "answer_trust_diagnostic",
        "tool_version": TOOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": facts["generated_at"],
        "summary": summary,
        "findings": findings,
        "facts": facts,
        "note": ("This report contains NO secret values and NO file contents — "
                 "only filenames, counts, booleans and recommendations. It is "
                 "safe to share back for a remediation proposal."),
    }


def compare_reports(current, old_path):
    with open(old_path, encoding="utf-8") as f:
        old = json.load(f)

    def idmap(rep):
        return {f["id"]: f for f in rep.get("findings", []) if f.get("id")}

    cur, oldm = idmap(current), idmap(old)
    new_ids = sorted(set(cur) - set(oldm))
    resolved_ids = sorted(set(oldm) - set(cur))
    persist_ids = sorted(set(cur) & set(oldm))
    sev_changed = [{"id": i, "from": oldm[i]["severity"], "to": cur[i]["severity"]}
                   for i in persist_ids if oldm[i]["severity"] != cur[i]["severity"]]
    return {
        "compared_against": os.path.abspath(old_path),
        "old_generated_at": old.get("generated_at"),
        "new": [cur[i] for i in new_ids],
        "resolved": [{"id": i, "severity": oldm[i]["severity"], "title": oldm[i]["title"]}
                     for i in resolved_ids],
        "persisting": [cur[i] for i in persist_ids],
        "severity_changed": sev_changed,
    }


def render_markdown(report):
    lines = [
        "# Answer Trust Diagnostic Report",
        "",
        "Generated: %s  |  Project: %s  |  Tool: v%s (schema v%s)" % (
            report["generated_at"], report["facts"].get("project_dir", ""),
            report.get("tool_version", "?"), report.get("schema_version", "?")),
        "",
        "**Summary:** %d high · %d medium · %d low · %d info" % (
            report["summary"]["high"], report["summary"]["medium"],
            report["summary"]["low"], report["summary"]["info"]),
        "",
        "> %s" % report["note"],
        "",
    ]
    for f in report["findings"]:
        hours = f.get("self_fix_hours")
        hours_txt = " · self-fix ~%s h" % hours if hours else ""
        lines.append("### [%s] %s" % (f["severity"].upper(), f["title"]))
        lines.append("- Finding ID: `%s`%s" % (f.get("id", "?"), hours_txt))
        if f["detail"]:
            lines.append("- %s" % f["detail"])
        if f["advice"]:
            lines.append("- **Advice:** %s" % f["advice"])
        lines.append("")
    cmp_ = report.get("compare")
    if cmp_:
        lines += ["## Comparison with previous report", "",
                  "- Baseline: `%s` (generated %s)" % (
                      cmp_["compared_against"], cmp_.get("old_generated_at") or "unknown"), ""]
        for label, key, mark in (("Resolved", "resolved", "RESOLVED"),
                                 ("New", "new", "NEW")):
            if cmp_[key]:
                lines.append("**%s:**" % label)
                for r in cmp_[key]:
                    lines.append("- %s `%s` %s" % (mark, r["id"], r["title"]))
                lines.append("")
        if cmp_["severity_changed"]:
            lines.append("**Severity changed:**")
            for s in cmp_["severity_changed"]:
                lines.append("- CHANGED `%s`: %s -> %s" % (s["id"], s["from"], s["to"]))
            lines.append("")
        if cmp_["persisting"]:
            lines.append("**Persisting** (not yet fixed, follow the advice):")
            for p in cmp_["persisting"]:
                lines.append("- `%s` %s" % (p["id"], p["title"]))
            lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Answer trust diagnostic (read-only)")
    ap.add_argument("project_dir", nargs="?", default=os.getcwd())
    ap.add_argument("--output", default=None,
                    help="Directory for reports (default: <project_dir>/trust_diag_reports)")
    ap.add_argument("--compare", metavar="OLD_REPORT.json",
                    help="Compare with a previous JSON report (new/resolved/persisting)")
    ap.add_argument("--json", action="store_true", help="Also print JSON to stdout")
    args = ap.parse_args()

    report = gather(args.project_dir)
    if args.compare:
        if not os.path.exists(args.compare):
            print("Compare failed: old report not found: %s" % args.compare)
            sys.exit(2)
        try:
            report["compare"] = compare_reports(report, args.compare)
        except Exception as e:
            print("Compare failed: old report unreadable (%s)" % type(e).__name__)
            sys.exit(2)

    outdir = args.output or os.path.join(args.project_dir, "trust_diag_reports")
    os.makedirs(outdir, exist_ok=True)
    md_path = os.path.join(outdir, "trust_diagnostic_report.md")
    js_path = os.path.join(outdir, "trust_diagnostic_report.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    s = report["summary"]
    print("Answer trust diagnostic complete.")
    print("  high: %d | medium: %d | low: %d | info: %d" % (
        s["high"], s["medium"], s["low"], s["info"]))
    cmp_ = report.get("compare")
    if cmp_:
        print("  compare: %d new | %d resolved | %d persisting" % (
            len(cmp_["new"]), len(cmp_["resolved"]), len(cmp_["persisting"])))
    print("Report: %s" % md_path)
    print("        %s" % js_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
