import json
import subprocess
import sys
from pathlib import Path

import audit_page_content
import pytest
from PIL import Image


def make_spec(tmp_path):
    source = json.loads((Path(__file__).resolve().parents[1] / "examples/page-spec.example.json").read_text(encoding="utf-8"))
    slide = source["slides"][0]
    slide["required_visible_values"] = ["增长 32%"]
    slide["image_status"] = "generated"
    image = tmp_path / slide["image_file"]
    image.parent.mkdir()
    Image.new("RGB", (160, 90), "white").save(image)
    path = tmp_path / "page-spec.json"
    path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    return path, source


def test_detects_missing_numeric_and_stale_transcription(tmp_path):
    path, spec = make_spec(tmp_path)
    slide = spec["slides"][0]
    observation = audit_page_content.template(path, [slide])
    observation["slides"][0].update(status="complete", observed_text="让数字服务真正走进田间\n以可信、易用的数字服务连接农户与产业资源\n增长 23%")
    report = audit_page_content.audit(path, [slide], observation)
    assert report["issues"] == 1
    assert report["slides"][0]["findings"][0]["missing_numbers"] == ["32%"]
    observation["slides"][0]["observed_text"] = observation["slides"][0]["observed_text"].replace("23%", "32%")
    assert audit_page_content.audit(path, [slide], observation)["pass"]
    Image.new("RGB", (160, 90), "black").save(tmp_path / slide["image_file"])
    with pytest.raises(ValueError, match="hash changed"):
        audit_page_content.audit(path, [slide], observation)


def test_new_policy_reports_each_missing_literal_once_and_keeps_reasoning_off_page(tmp_path):
    path, spec = make_spec(tmp_path)
    spec["content_policy"] = "1.1"
    spec["workflow"] = {"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                        "outline_ref": "Complete outline in message 4"}
    spec["style"].update(decision="locked-reference", authorization="Keep supplied style")
    slide = spec["slides"][0]
    slide["explanation"] = "Internal explanatory sentence"
    slide["source_refs"] = ["Internal source scope"]
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    observation = audit_page_content.template(path, [slide])
    entry = observation["slides"][0]
    entry.update(status="complete", observed_text="让数字服务真正走进田间\n以可信、易用的数字服务连接农户与产业资源")
    findings = audit_page_content.audit(path, [slide], observation)["slides"][0]["findings"]
    assert [finding["expected"] for finding in findings] == ["增长 32%"]
    entry["observed_text"] += "\n增长 32%"
    assert audit_page_content.audit(path, [slide], observation)["pass"]


def test_partial_observation_cannot_pass_strict_gate(tmp_path):
    path, spec = make_spec(tmp_path)
    observation = audit_page_content.template(path, spec["slides"])
    report = audit_page_content.audit(path, spec["slides"], observation)
    assert not report["pass"]
    assert report["incomplete"] == 1
    assert all(finding["status"] == "needs_review" for finding in report["slides"][0]["findings"])


def test_chinese_adjacent_numbers_and_units():
    assert audit_page_content.numbers("增长32%，达到1,200万；单价12.5元") == ["32%", "1,200", "12.5"]
    assert audit_page_content.compact_number("1,200") == audit_page_content.compact_number("1200")


def test_cli_creates_transcription_template(tmp_path):
    path, _ = make_spec(tmp_path)
    target = tmp_path / "observations.json"
    script = Path(__file__).resolve().parents[1] / "scripts/audit_page_content.py"
    result = subprocess.run([sys.executable, str(script), str(path), str(target), "--init", "--slide", "s01"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    observation = json.loads(target.read_text(encoding="utf-8"))
    assert len(observation["slides"][0]["image_sha256"]) == 64


def test_required_numeric_values_must_not_match_inside_larger_numbers():
    from audit_page_content import text_present
    assert not text_present("32%", "132%")
    assert not text_present("351", "1351")
    assert not text_present("32", "32%")
    assert text_present("32%", "覆盖率32%，另一个值132%")


@pytest.mark.parametrize(("expected", "observed", "matches"), [
    ("32万元", "投资额132万元，涉及32个项目", False),
    ("32万元", "投资额-32万元，涉及32个项目", False),
    ("32%", "覆盖率132%，另一项为32 %", True),
    ("32", "覆盖率32%\n实测32个", True),
    ("金额 1,200 万元", "金额1200万元", True),
    ("2.5万元", "12.5万元，涉及2.5吨", False),
    ("5万元", ".5万元，涉及5个项目", False),
    ("32", "项目编号SKU32", False),
    ("-5%", "YoY− 5%", True),
    ("2020-2024", "2020 - 2024", True),
])
def test_numbers_are_checked_at_the_matched_text_position(expected, observed, matches):
    assert audit_page_content.text_present(expected, observed) is matches


@pytest.mark.parametrize("minus", ["−", "－", "﹣", "-"])
def test_negative_signs_keep_their_numeric_meaning(tmp_path, minus):
    assert not audit_page_content.text_present("增长5%", f"增长{minus}5%")
    assert audit_page_content.text_present("增长-5%", f"增长{minus}5%")
    path, spec = make_spec(tmp_path)
    slide = spec["slides"][0]
    slide["required_visible_values"] = ["增长5%"]
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    observations = audit_page_content.template(path, [slide])
    observations["slides"][0].update(status="complete", observed_text="\n".join(
        [e["text"] for e in slide["elements"] if e["kind"] == "text"] + [f"增长{minus}5%超出预期"]))
    result = audit_page_content.audit(path, [slide], observations)
    assert not result["pass"] and result["issues"] == 1


def test_renderer_spacing_keeps_the_sign_without_turning_ranges_into_negatives():
    match = audit_page_content.text_present
    assert match("同比 −6.9%", "同比 − 6.9%")
    assert match("同比 +3.2%", "同比 + 3.2%")
    assert not match("同比 −6.9%", "同比 6.9%")
    assert not match("同比 −6.9%", "同比 − 16.9%")
    assert audit_page_content.numbers("2019 - 2020") == ["2019", "2020"]


@pytest.mark.parametrize(("expected", "observed", "matches"), [
    ("样本编号 A-32", "样本编号 A - 32", True),
    ("样本编号 A - 32", "样本编号 A-32", True),
    ("样本编号 SKU-32", "样本编号 SKU - 32", True),
    ("样本编号 A-32", "样本编号 A - 320", False),
    ("-32", "样本编号 A - 32", False),
    ("32", "样本编号 A-32", False),
    ("32万元", "同比 - 32 万元", False),
    ("同比-32万元", "同比 - 32 万元", True),
    ("-32万元", "Q1 - 32 万元", True),
    ("32万元", "Q1 - 32 万元", False),
    ("同比-.5%", "同比 - .5%", True),
    (".5%", "同比 - .5%", False),
    ("-32%", "YoY - 32%", True),
    ("2019-2020", "2019 -2020", True),
    ("2019-2020", "2019- 2020", True),
    ("2019-2020", "2019 − 2020", True),
    ("20%-30%", "20% - 30%", True),
    ("排放量32", "排放量32e6", False),
    ("排放量32", "排放量32E-6，另测32", False),
    ("排放量 32e-6", "排放量32E−6", True),
    ("32e6", "32e60", False),
    ("32e6", "- 32e6", False),
    ("覆盖率32%", "覆盖率32\n %", True),
    ("覆盖率32", "覆盖率32\r\n %", False),
    ("32‰", "32\n‰", True),
])
def test_number_boundaries_preserve_identifiers_signs_exponents_and_wrapped_units(expected, observed, matches):
    assert audit_page_content.text_present(expected, observed) is matches


@pytest.mark.parametrize(("expected", "observed", "passed"), [
    ("样本编号 A-32", "样本编号 A - 32", True),
    ("32万元", "同比 - 32 万元", False),
    ("排放量32", "排放量32e6", False),
    ("覆盖率32%", "覆盖率32\n%", True),
])
def test_full_content_audit_checks_the_required_literal(tmp_path, expected, observed, passed):
    path, spec = make_spec(tmp_path)
    slide = spec["slides"][0]
    slide["required_visible_values"] = [expected]
    observations = audit_page_content.template(path, [slide])
    text = [element["text"] for element in slide["elements"] if element["kind"] == "text"]
    observations["slides"][0].update(status="complete", observed_text="\n".join([*text, observed]))
    assert audit_page_content.audit(path, [slide], observations)["pass"] is passed


@pytest.mark.parametrize("bad", [
    "[]", '{"version":"1.0","slides":null}', '{"version":"1.0","slides":[null]}',
    '{"version":"1.0","slides":[{"id":[]}]}', '{"version":"1.0","slides":[',
])
@pytest.mark.parametrize("selected", [False, True])
def test_content_cli_reports_malformed_records_before_filtering(tmp_path, monkeypatch, capsys, bad, selected):
    spec, _ = make_spec(tmp_path)
    observations = tmp_path / "external.json"
    observations.write_text(bad, encoding="utf-8")
    arguments = ["audit_page_content.py", str(spec), str(observations)]
    if selected:
        arguments += ["--slide", "s01"]
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit) as error:
        audit_page_content.main()
    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert f"Invalid observation file {observations}" in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize("target", ["spec", "observations", "image", "report"])
def test_content_cli_only_writes_a_separate_report(tmp_path, monkeypatch, capsys, target):
    spec, document = make_spec(tmp_path)
    observations = tmp_path / "observations.json"
    observations.write_text(json.dumps(audit_page_content.template(spec, document["slides"])), encoding="utf-8")
    image = tmp_path / document["slides"][0]["image_file"]
    files = {"spec": spec, "observations": observations, "image": image}
    original = {path: path.read_bytes() for path in files.values()}
    destination = files.get(target, tmp_path / "report.json")
    subdir = destination.parent / "subdir"
    subdir.mkdir()
    alias = subdir / ".." / destination.name
    monkeypatch.setattr(sys, "argv", ["audit_page_content.py", str(spec), str(observations),
                                      "--output", str(alias)])
    if target == "report":
        audit_page_content.main()
        assert json.loads(destination.read_bytes())["incomplete"] == 1
    else:
        with pytest.raises(SystemExit) as error:
            audit_page_content.main()
        assert error.value.code == 2
        assert "must not overwrite" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in files.values()} == original
