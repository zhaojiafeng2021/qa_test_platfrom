"""JaCoCo 报告生成与存储：.exec → XML/HTML → 解析 → 上传 MinIO → 返回结构化数据"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.minio_client import get_minio_client
from app.modules.coverage_java.xml_parser import parse_jacoco_xml

logger = get_logger(__name__)


class ReportGenerateError(Exception):
    """报告生成失败"""
    pass


async def _run_jacococli(args: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    """异步执行 java -jar jacococli.jar ..."""
    jacoco_cli = Path(settings.jacoco_cli_jar_path)
    cmd = ["java", "-jar", str(jacoco_cli)] + args
    logger.info(f"Running jacococli: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ReportGenerateError(f"jacococli timeout after {timeout}s")
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    return proc.returncode or 0, output


_MISMATCH_RE = re.compile(r"Execution data for class (\S+) does not match")


def _to_unit_fqn(vm_name: str) -> str:
    """VM 内部类名 → 方法单元 key 的类部分

    com/example/Outer$Inner → com.example.Outer.Inner（与 JavaMethodParser 一致）；
    匿名类 / lambda 归外层：com/example/Outer$1 → com.example.Outer
    """
    parts = vm_name.replace("/", ".").split("$")
    kept = [parts[0]]
    for p in parts[1:]:
        if not p or p[0].isdigit():
            break
        kept.append(p)
    return ".".join(kept)


def parse_mismatch_classes(log: str) -> list[str]:
    """从 jacococli report 输出中提取 class ID 不一致的类，返回去重排序的 FQN

    结果可直接作为 LedgerMigrator.migrate 的 exclude_classes。
    """
    return sorted({_to_unit_fqn(m.group(1)) for m in _MISMATCH_RE.finditer(log or "")})


class JaCoCoReportService:
    """生成 + 解析 + 上传 JaCoCo 报告"""

    def __init__(self):
        self.minio = get_minio_client()

    async def generate_xml_html(
        self,
        exec_file: Path,
        classfiles_dir: Path,
        sourcefiles_dir: Path,
        output_dir: Path,
    ) -> tuple[Path, Path, list[str]]:
        """调用 jacococli 生成 XML 和 HTML 报告

        Returns:
            (xml_path, html_dir, mismatch_classes)
            mismatch_classes：exec 中与 classfiles 的 class ID 不一致的类（FQN，`.` 分隔）
        """
        xml_path, log = await self.generate_report(
            [exec_file], classfiles_dir, sourcefiles_dir, output_dir, html=True,
        )
        html_dir = output_dir / "html"
        if not html_dir.exists():
            raise ReportGenerateError(f"jacococli did not produce HTML at {html_dir}: {log}")
        return xml_path, html_dir, parse_mismatch_classes(log)

    async def generate_report(
        self,
        exec_files: list[Path],
        classfiles_dir: Path,
        sourcefiles_dir: Path,
        output_dir: Path,
        html: bool = False,
    ) -> tuple[Path, str]:
        """按指定 class 生成 XML（可选 HTML）报告；返回 (xml_path, jacococli 输出)

        exec_files 可传多个，jacococli 会先合并再出报告（账本用 head commit 的 class 出累积报告）。
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        xml_path = output_dir / "jacoco.xml"

        args = [
            "report", *[str(f) for f in exec_files],
            "--classfiles", str(classfiles_dir),
            "--sourcefiles", str(sourcefiles_dir),
            "--xml", str(xml_path),
        ]
        if html:
            args += ["--html", str(output_dir / "html")]
        code, log = await _run_jacococli(args, cwd=output_dir)
        if code != 0:
            raise ReportGenerateError(f"jacococli report failed: exit={code}, log={log}")
        if not xml_path.exists():
            raise ReportGenerateError(f"jacococli did not produce XML at {xml_path}: {log}")
        return xml_path, log

    async def merge_exec(self, exec_files: list[Path], dest_file: Path) -> Path:
        """jacococli merge：同一 class ID 的探针按位或，结果精确"""
        if not exec_files:
            raise ReportGenerateError("merge_exec: no exec files")
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        args = ["merge", *[str(f) for f in exec_files], "--destfile", str(dest_file)]
        code, log = await _run_jacococli(args, cwd=dest_file.parent)
        if code != 0 or not dest_file.exists():
            raise ReportGenerateError(f"jacococli merge failed: exit={code}, log={log}")
        return dest_file

    def parse_xml(self, xml_path: Path) -> dict[str, Any]:
        """解析 JaCoCo XML，返回 {overall, files}"""
        content = xml_path.read_text(encoding="utf-8")
        return parse_jacoco_xml(content)

    def upload_artifacts(
        self,
        task_id: int,
        run_id: int,
        service_name: str,
        xml_path: Path,
        html_dir: Path,
        exec_file: Path,
        build_log: str,
    ) -> dict[str, str]:
        """上传产物到 MinIO，返回 object_name 字典

        MinIO 路径规则：coverage/{task_id}/{run_id}/{service_name}/{xml|html.zip|exec|build.log}
        HTML 目录会先 zip 再上传（MinIO 不适合存大量小文件）。
        """
        import zipfile
        import io

        base = f"coverage/{task_id}/{run_id}/{service_name}"

        # 1. XML
        xml_obj = f"{base}/jacoco.xml"
        self.minio.upload_file(
            xml_obj,
            xml_path.read_bytes(),
            content_type="application/xml",
        )

        # 2. HTML 目录 → zip
        html_zip_buf = io.BytesIO()
        with zipfile.ZipFile(html_zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in html_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=str(f.relative_to(html_dir)))
        html_obj = f"{base}/jacoco-html.zip"
        self.minio.upload_file(html_obj, html_zip_buf.getvalue(), content_type="application/zip")

        # 3. .exec
        exec_obj = f"{base}/coverage.exec"
        self.minio.upload_file(exec_obj, exec_file.read_bytes(), content_type="application/octet-stream")

        # 4. build log
        log_obj = f"{base}/build.log"
        self.minio.upload_file(log_obj, build_log.encode("utf-8"), content_type="text/plain")

        return {
            "xml_report_path": xml_obj,
            "html_report_path": html_obj,
            "exec_file_path": exec_obj,
            "build_log_path": log_obj,
        }

    def upload_source_snapshot(
        self,
        task_id: int,
        run_id: int,
        service_name: str,
        sourcefiles_dir: Path,
        file_paths: list[str],
    ) -> str | None:
        """把报告涉及的源码文件打包为 sources.zip 上传 MinIO

        zip 内 arcname 与 line_coverage_json 的 key 一致（如 com/example/Foo.java），
        便于按 file_path 直接读取。没有任何源码文件时返回 None。
        """
        import io
        import zipfile

        buf = io.BytesIO()
        added = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in file_paths:
                src = sourcefiles_dir / rel
                if src.is_file():
                    zf.write(src, arcname=rel)
                    added += 1
                else:
                    logger.warning(f"[{service_name}] source file missing for snapshot: {src}")
        if added == 0:
            return None

        obj = f"coverage/{task_id}/{run_id}/{service_name}/sources.zip"
        self.minio.upload_file(obj, buf.getvalue(), content_type="application/zip")
        return obj

    def read_source_from_snapshot(self, snapshot_path: str, file_path: str) -> str | None:
        """从 MinIO 的 sources.zip 读取单个源码文件；不存在返回 None"""
        import io
        import zipfile

        data = self.minio.download_file(snapshot_path)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            try:
                raw = zf.read(file_path)
            except KeyError:
                return None
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
