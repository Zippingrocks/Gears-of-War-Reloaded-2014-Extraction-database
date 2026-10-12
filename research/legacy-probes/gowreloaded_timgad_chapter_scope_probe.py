from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PACKAGE_TOKEN_RE = re.compile(
    r"\bSP_Timgad_(?:"
    r"Intro|P|World|BD1|BD1Lighting|Lighting|Audio|Battle1_Cine|"
    r"Cine[3-5]|S0[1-7]b?|S01_Dropped|S0[1-7]b?Lighting|"
    r"Scripting_[1-5]|Zone[1-4]_VFX"
    r")\b",
    re.IGNORECASE,
)


def parse_tags(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def tag_value(tags: list[dict[str, Any]], name: str) -> Any:
    for tag in tags:
        if tag.get("name") == name or tag.get("base_name") == name:
            return tag.get("decoded")
    return None


def short_string(value: Any) -> str:
    if isinstance(value, dict):
        if "path" in value:
            return str(value["path"])
        if "ref" in value:
            return str(value["ref"])
    if isinstance(value, list):
        return ",".join(short_string(item) for item in value[:8])
    if value is None:
        return ""
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Timgad A chapter/streaming boundary markers.")
    parser.add_argument("--properties-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    properties_csv = Path(args.properties_csv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    interesting_classes = {
        "LevelStreamingKismet",
        "SeqAct_ChapterComplete",
        "SeqAct_DisplayChapterTitle",
        "SeqAct_PrepareMapChange",
        "SeqAct_LevelVisibility",
        "SeqAct_MultiLevelStreaming",
        "SeqAct_WaitForLevelsVisible",
        "SeqVar_Named",
        "SequenceFrame",
        "WarCheckpoint",
    }

    rows: list[dict[str, str]] = []
    package_refs: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    marker_rows: list[dict[str, str]] = []
    checkpoint_rows: list[dict[str, str]] = []
    streaming_rows: list[dict[str, str]] = []
    comment_rows: list[dict[str, str]] = []

    with properties_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            package = row.get("package", "")
            cls = row.get("class_name", "")
            text = row.get("search_text", "")
            tags = parse_tags(row.get("all_tags_json", ""))
            refs = sorted({match.group(0) for match in PACKAGE_TOKEN_RE.finditer(text)})
            if package.lower() == "sp_timgad_p.war":
                refs.append("SP_Timgad_P")
            for ref in refs:
                package_refs[ref] += 1

            title = short_string(tag_value(tags, "DisplayChapter"))
            completed = short_string(tag_value(tags, "ChapterCompleted"))
            main_level = short_string(tag_value(tags, "MainLevelName"))
            package_name = short_string(tag_value(tags, "PackageName"))
            map_name = short_string(tag_value(tags, "MapName"))
            checkpoint = short_string(tag_value(tags, "CheckpointName"))
            comment = short_string(tag_value(tags, "ObjComment"))
            location = short_string(tag_value(tags, "Location"))

            is_marker = (
                cls in interesting_classes
                or title
                or completed
                or main_level
                or package_name
                or map_name
                or checkpoint
                or comment
                or refs
                or "chapter" in text.lower()
                or "checkpoint" in text.lower()
                or "mapchange" in text.lower()
            )
            if not is_marker:
                continue

            class_counts[cls] += 1
            out_row = {
                "package": package,
                "export_index": row.get("export_index", ""),
                "class_name": cls,
                "object_name": row.get("object_name", ""),
                "full_path": row.get("full_path", ""),
                "display_chapter": title,
                "chapter_completed": completed,
                "main_level_name": main_level,
                "package_name": package_name,
                "map_name": map_name,
                "checkpoint_name": checkpoint,
                "obj_comment": comment,
                "location": location,
                "package_refs": ";".join(refs),
            }
            rows.append(out_row)
            if title or completed or main_level:
                marker_rows.append(out_row)
            if checkpoint or map_name:
                checkpoint_rows.append(out_row)
            if cls == "LevelStreamingKismet" or package_name or refs:
                streaming_rows.append(out_row)
            if comment:
                comment_rows.append(out_row)

    fields = [
        "package",
        "export_index",
        "class_name",
        "object_name",
        "full_path",
        "display_chapter",
        "chapter_completed",
        "main_level_name",
        "package_name",
        "map_name",
        "checkpoint_name",
        "obj_comment",
        "location",
        "package_refs",
    ]

    def write_csv(name: str, data: list[dict[str, str]]) -> None:
        with (out_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)

    write_csv("timgad_a_chapter_scope_markers.csv", marker_rows)
    write_csv("timgad_a_chapter_scope_checkpoints.csv", checkpoint_rows)
    write_csv("timgad_a_chapter_scope_streaming.csv", streaming_rows)
    write_csv("timgad_a_chapter_scope_comments.csv", comment_rows[:1000])

    package_hint_groups: dict[str, list[str]] = defaultdict(list)
    for row in streaming_rows + checkpoint_rows + marker_rows:
        key = row["package"]
        note = row["package_refs"] or row["map_name"] or row["main_level_name"] or row["display_chapter"] or row["checkpoint_name"]
        if note and len(package_hint_groups[key]) < 80:
            package_hint_groups[key].append(note)

    summary = {
        "properties_csv": str(properties_csv),
        "rows_scanned": sum(class_counts.values()),
        "marker_rows": len(marker_rows),
        "checkpoint_rows": len(checkpoint_rows),
        "streaming_rows": len(streaming_rows),
        "comment_rows": len(comment_rows),
        "class_counts": class_counts.most_common(),
        "package_refs": package_refs.most_common(),
        "package_hint_groups": package_hint_groups,
    }
    (out_dir / "timgad_a_chapter_scope_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
