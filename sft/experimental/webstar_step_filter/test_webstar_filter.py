"""Offline tests for WebSTAR filter v1. No API calls are made."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from .common import StepKey, load_source_rows, sha256_text
from .decide_steps import decide
from .filter_copy import build_filtered_copy, validate_coverage
from .grade_steps import build_judge_messages, parse_score
from .prompt import PROMPT_VERSION, STEP_JUDGE_PROMPT
from .sample_calibration import select_calibration
from .visuals import annotate_action


def judge_response(score=7, alternatives=3):
    items = "\n".join(
        f"{index}. action {index}; feasible; likely outcome; worse"
        for index in range(1, alternatives + 1))
    return (
        "Screenshot analysis:\nstate\n"
        "Proposed action review:\ncorrect\n"
        f"Alternative analysis:\n{items}\n"
        "Evaluation:\ncorrect and optimal\n"
        f"Expected value: {score}"
    )


def response(action="left_click", think="grounded", coordinate="[100, 120]"):
    parts = [f"<think>{think}</think>", "<tool_call>",
             "<function=computer_use>",
             f"<parameter=action>\n{action}\n</parameter>"]
    if coordinate:
        parts.append(f"<parameter=coordinate>\n{coordinate}\n</parameter>")
    parts.extend(["</function>", "</tool_call>"])
    return "\n".join(parts)


def sample(run, domain, task_id, step, n_steps, target, image_name,
           history_text=""):
    messages = [{
        "role": "user",
        "content": [{"type": "image", "path": f"images/{image_name}"},
                    {"type": "text", "text": "current state"}],
    }]
    if history_text:
        messages.insert(0, {
            "role": "assistant",
            "content": [{"type": "text", "text": history_text}],
        })
    return {
        "messages": messages,
        "response": target,
        "meta": {"run": run, "domain": domain, "task_id": task_id,
                 "step": step, "n_steps": n_steps, "orig_steps": n_steps},
    }


def write_source(root, name, rows):
    source = root / name
    (source / "images").mkdir(parents=True)
    for index in range(1, 10):
        Image.new("RGB", (320, 240), "white").save(
            source / "images" / f"img{index}.png")
    with (source / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return source


class WebStarFilterTests(unittest.TestCase):
    def test_prompt_follows_paper_four_stage_contract(self):
        self.assertEqual(PROMPT_VERSION, "webstar-paper-four-stage-v2")
        for heading in ("1. Screenshot analysis", "2. Proposed action review",
                        "3. Alternative analysis", "4. Evaluation"):
            self.assertIn(heading, STEP_JUDGE_PROMPT)
        self.assertIn("exactly three distinct alternative", STEP_JUDGE_PROMPT)
        self.assertIn("0: irreversible error or guaranteed task failure",
                      STEP_JUDGE_PROMPT)
        self.assertIn("5: partially correct or suboptimal action",
                      STEP_JUDGE_PROMPT)
        self.assertIn("10: unambiguously helpful step with no superior alternative",
                      STEP_JUDGE_PROMPT)

    def test_score_parser_uses_final_expected_value(self):
        self.assertEqual(parse_score(judge_response(7)), 7)
        with self.assertRaises(ValueError):
            parse_score("score is probably seven")
        with self.assertRaisesRegex(ValueError, "exactly alternatives"):
            parse_score(judge_response(7, alternatives=2))
        with self.assertRaisesRegex(ValueError, "exactly alternatives"):
            parse_score(judge_response(7, alternatives=4))

    def test_official_revised_contract_matches_reference_parser_scope(self):
        self.assertEqual(
            parse_score("free-form eight-stage analysis\nExpected value: 6",
                        contract="official-revised"), 6)
        with self.assertRaises(ValueError):
            parse_score("no final score", contract="official-revised")

    def test_visual_annotation_and_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            Image.new("RGB", (400, 300), "white").save(path)
            full, crop = annotate_action(
                path, ["pyautogui.click(100, 120)"], crop_size=200)
            self.assertTrue(full.startswith(b"\x89PNG"))
            self.assertTrue(crop.startswith(b"\x89PNG"))
            crop_path = Path(tmp) / "crop.png"
            crop_path.write_bytes(crop)
            with Image.open(crop_path) as crop_image:
                self.assertEqual(crop_image.size, (200, 200))

    def test_calibration_is_unique_and_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = {}
            for source_name in ("v16-main", "v11new-500"):
                rows = []
                for task_no in range(8):
                    task_id = f"{source_name}-{task_no}"
                    rows.extend([
                        sample("run", "calc", task_id, 1, 4,
                               response("left_click", "x" * (400 + task_no)), "img1.png"),
                        sample("run", "calc", task_id, 2, 4,
                               response("left_click", "retrying the same target"), "img2.png"),
                        sample("run", "calc", task_id, 3, 4,
                               response("key", "The previous action was incorrect; fixing the mistake.", None),
                               "img3.png"),
                        sample("run", "calc", task_id, 4, 4,
                               response("terminate", "All requirements are complete.", None),
                               "img4.png"),
                    ])
                sources[source_name] = write_source(root, source_name, rows)
            index, _ = load_source_rows(sources)
            first = select_calibration(
                index, seed=42, random_count=2, terminal_count=2,
                recovery_count=2, long_count=2, risky_count=2)
            second = select_calibration(
                index, seed=42, random_count=2, terminal_count=2,
                recovery_count=2, long_count=2, risky_count=2)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 10)
            keys = [StepKey.from_dict(row) for row in first]
            self.assertEqual(len(keys), len(set(keys)))
            self.assertEqual({row["stratum"] for row in first},
                             {"random", "terminal", "recovery",
                              "long_think", "risky"})

    def test_official_threshold_and_terminal_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                sample("run", "calc", "task", 1, 2,
                       response("left_click"), "img1.png"),
                sample("run", "calc", "task", 2, 2,
                       response("terminate", coordinate=None), "img2.png"),
            ]
            source = write_source(root, "source", rows)
            index, _ = load_source_rows({"source": source})
            keys = sorted(index)
            scores = {
                keys[0]: [{**keys[0].as_dict(), "pass_id": "p1", "score": 6,
                           "source_response_sha256": sha256_text(rows[0]["response"])}],
                keys[1]: [{**keys[1].as_dict(), "pass_id": "p1", "score": 5,
                           "source_response_sha256": sha256_text(rows[1]["response"])}],
            }
            decisions = decide(index, scores)
            self.assertEqual(decisions[0]["decision"], "keep")
            self.assertEqual(decisions[1]["decision"], "review")

            override = {keys[1]: {"decision": "keep", "reason": "manually verified",
                                  "reviewer": "test"}}
            decisions = decide(index, scores, override)
            self.assertEqual(decisions[1]["decision"], "keep")
            self.assertEqual(decisions[1]["decision_source"], "manual_override")

    def test_filter_drops_only_target_row_and_preserves_later_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            step1 = response("left_click", "step one")
            step2 = response("left_click", "bad step two")
            step3 = response("terminate", "task complete", None)
            rows = [
                sample("run", "calc", "task", 1, 3, step1, "img1.png"),
                sample("run", "calc", "task", 2, 3, step2, "img2.png", step1),
                sample("run", "calc", "task", 3, 3, step3, "img3.png", step2),
            ]
            source = write_source(root, "source", rows)
            index, _ = load_source_rows({"source": source})
            decisions = {}
            for key in sorted(index):
                decision = "drop" if key.step == 2 else "keep"
                decisions[key] = {
                    **key.as_dict(), "decision": decision,
                    "terminal": key.step == 3,
                    "source_response_sha256": sha256_text(
                        index[key].sample["response"]),
                }
            policy = root / "policy.json"
            policy.write_text("{}\n")
            out = root / "filtered"
            version = build_filtered_copy(
                {"source": source}, decisions,
                {"source": Path("/gpfs/source")}, out, policy,
                expected_rows=3)
            output_rows = [json.loads(line) for line in
                           (out / "source_train_swift_abs.jsonl").read_text().splitlines()]
            self.assertEqual(len(output_rows), 2)
            self.assertIn("bad step two", output_rows[-1]["messages"][0]["content"])
            self.assertNotIn(step2, [row["messages"][-1]["content"]
                                    for row in output_rows])
            self.assertTrue(output_rows[0]["images"][0].startswith("/gpfs/source/images/"))
            self.assertEqual(version["decision_counts"], {"drop": 1, "keep": 2})

            bad = dict(decisions)
            terminal_key = max(index)
            bad[terminal_key] = {**bad[terminal_key], "decision": "drop"}
            with self.assertRaisesRegex(ValueError, "terminal target is not kept"):
                validate_coverage(index, bad, expected_rows=3)

    def test_coverage_review_and_response_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                sample("run", "calc", "task", 1, 2,
                       response("left_click"), "img1.png"),
                sample("run", "calc", "task", 2, 2,
                       response("terminate", coordinate=None), "img2.png"),
            ]
            source = write_source(root, "source", rows)
            index, _ = load_source_rows({"source": source})
            keys = sorted(index)
            decisions = {
                key: {**key.as_dict(), "decision": "keep",
                      "source_response_sha256": sha256_text(
                          index[key].sample["response"])}
                for key in keys
            }
            with self.assertRaisesRegex(ValueError, "coverage mismatch"):
                validate_coverage(index, {keys[0]: decisions[keys[0]]}, 2)

            review = dict(decisions)
            review[keys[0]] = {**review[keys[0]], "decision": "review"}
            with self.assertRaisesRegex(ValueError, "unresolved review"):
                validate_coverage(index, review, 2)

            drift = dict(decisions)
            drift[keys[0]] = {**drift[keys[0]],
                              "source_response_sha256": "not-the-source-hash"}
            with self.assertRaisesRegex(ValueError, "response hash mismatch"):
                validate_coverage(index, drift, 2)

    def test_absolute_image_outside_source_cannot_be_remapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external = root / "external.png"
            Image.new("RGB", (320, 240), "white").save(external)
            row = sample("run", "calc", "task", 1, 1,
                         response("terminate", coordinate=None), "img1.png")
            row["messages"][0]["content"][0]["path"] = str(external)
            source = write_source(root, "source", [row])
            index, _ = load_source_rows({"source": source})
            key = next(iter(index))
            decisions = {key: {
                **key.as_dict(), "decision": "keep", "terminal": True,
                "source_response_sha256": sha256_text(row["response"]),
            }}
            policy = root / "policy.json"
            policy.write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "outside source build"):
                build_filtered_copy(
                    {"source": source}, decisions,
                    {"source": Path("/gpfs/source")}, root / "filtered",
                    policy, expected_rows=1)

    def test_judge_messages_use_pre_action_state_and_hide_teacher_think(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_source(root, "source", [
                sample("run", "calc", "task", 4, 4,
                       response("key", "SECRET TEACHER THINK", None), "img4.png")])
            index, _ = load_source_rows({"source": source})
            key = next(iter(index))

            result = root / "results" / "calc" / "task"
            result.mkdir(parents=True)
            Image.new("RGB", (320, 240), "white").save(result / "initial_state.png")
            Image.new("RGB", (320, 240), "white").save(result / "step1.png")
            Image.new("RGB", (320, 240), "white").save(result / "step2.png")
            Image.new("RGB", (320, 240), "white").save(result / "step3.png")
            Image.new("RGB", (320, 240), "white").save(result / "step4.png")
            raw = [
                {"step_num": 1, "action": "pyautogui.click(10, 20)",
                 "response": response("left_click"), "screenshot_file": "step1.png"},
                {"step_num": 2, "action": "pyautogui.click(30, 40)",
                 "response": response("left_click"), "screenshot_file": "step2.png"},
                {"step_num": 3, "action": "pyautogui.click(50, 60)",
                 "response": response("left_click"), "screenshot_file": "step3.png"},
                {"step_num": 4, "action": "pyautogui.hotkey('ctrl', 's')",
                 "response": response("key", "raw", None), "screenshot_file": "step4.png"},
            ]
            with (result / "traj.jsonl").open("w") as handle:
                for row in raw:
                    handle.write(json.dumps(row) + "\n")

            tasks = root / "tasks" / "examples" / "calc"
            tasks.mkdir(parents=True)
            (tasks / "task.json").write_text(json.dumps({"instruction": "Save the sheet."}))
            messages, evidence = build_judge_messages(
                key, index[key], root / "results", root / "tasks")
            text_parts = [part["text"] for part in messages[1]["content"]
                          if part["type"] == "text"]
            judge_text = "\n".join(text_parts)
            self.assertNotIn("SECRET TEACHER THINK", judge_text)
            self.assertIn("step 1: pyautogui.click(10, 20)", judge_text)
            self.assertIn("step 3: pyautogui.click(50, 60)", judge_text)
            self.assertIn("pyautogui.hotkey('ctrl', 's')", judge_text)
            self.assertNotIn("<parameter=coordinate>", judge_text)
            images = [part for part in messages[1]["content"]
                      if part["type"] == "image_url"]
            self.assertEqual(len(images), 3)  # image window remains capped at three
            self.assertEqual(evidence["raw_actions"], ["pyautogui.hotkey('ctrl', 's')"])


if __name__ == "__main__":
    unittest.main()
