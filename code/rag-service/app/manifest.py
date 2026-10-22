from pathlib import Path


SAFE_MANIFEST: dict[str, tuple[str, ...]] = {
    "business_rules": (
        "01_汇丰业务文件/贷款文件比对要求- V2 20261013.xlsx",
        "01_汇丰业务文件/贷款文件比对要求.xlsx",
        "01_汇丰业务文件/贷款用途常见描述.xlsx",
        "01_汇丰业务文件/FOL 贷款用途（流贷+固贷）.docx",
        "02_团队方案与作品/10_金融Campaign项目需求梳理及软件策划.md",
        "02_团队方案与作品/12_金融Campaign项目需求梳理及软件策划_改进版.md",
    ),
    "project_design": (
        "01_汇丰业务文件/业务时序图/loan-review-sequence.mmd",
        "01_汇丰业务文件/业务时序图/loan-review-sequence.html",
        "02_团队方案与作品/09_汇丰跨境业务竞赛_系统构思.docx",
        "02_团队方案与作品/11_金融信息系统_业务点整理.docx",
        "03_会议记录/01_启动会材料_HBCN_AI_Agent_Kickoff.pptx",
    ),
}


def manifest_paths(source_root: Path, scope: str | None = None) -> list[tuple[str, Path]]:
    scopes = (scope,) if scope else tuple(SAFE_MANIFEST)
    root = source_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"业务资料目录不存在：{root}")

    result: list[tuple[str, Path]] = []
    for selected_scope in scopes:
        if selected_scope not in SAFE_MANIFEST:
            raise ValueError(f"不支持的资料范围：{selected_scope}")
        for relative_name in SAFE_MANIFEST[selected_scope]:
            candidate = (root / relative_name).resolve()
            if not candidate.is_relative_to(root):
                raise ValueError(f"白名单路径越界：{relative_name}")
            if "04设备API等文件" in candidate.parts:
                raise ValueError(f"敏感目录禁止进入知识库：{candidate}")
            if not candidate.is_file():
                raise FileNotFoundError(f"白名单文件不存在：{candidate}")
            result.append((selected_scope, candidate))
    return result
