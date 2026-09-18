"""本地文档转换、目录刷新和 PDF 分页阅读，不承担业务撰写决策。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


_PDFIUM_LOCK = threading.Lock()


def _resolve(value, roots: list[Path], *, exists: bool = True) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("文件路径不能为空")
    path = Path(value).expanduser()
    path = (path if path.is_absolute() else roots[0] / path).resolve()
    if not any(path == root or root in path.parents for root in roots):
        raise ValueError("文件路径必须位于当前授权目录内")
    if exists and not path.is_file():
        raise FileNotFoundError(f"文件不存在：{path.name}")
    return path


def _roots(base_dir, additional_dirs) -> list[Path]:
    return [Path(p).expanduser().resolve() for p in [base_dir, *(additional_dirs or [])]]


def _new_output(path: Path, source: Path) -> None:
    if path == source:
        raise ValueError("输出文件必须不同于原文件")
    if path.exists():
        raise FileExistsError(f"输出文件已存在，请选择新路径：{path.name}")


def _publish_files(pairs: list[tuple[Path, Path]]) -> None:
    # 独占创建防止覆盖既有成果；失败只清理本次已创建的输出。
    created = []
    try:
        for source, target in pairs:
            with target.open("xb") as output:
                created.append(target)
                with source.open("rb") as content:
                    shutil.copyfileobj(content, output)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _source_toc_count(path: Path) -> int:
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    instructions = [node.text or "" for node in root.iter(namespace + "instrText")]
    instructions.extend(node.get(namespace + "instr", "") for node in root.iter(namespace + "fldSimple"))
    return len(re.findall(r"\bTOC\b", " ".join(instructions), re.IGNORECASE))


def render_document(path, output_dir, base_dir, additional_dirs=None) -> dict[str, Any]:
    """在独立 Office 进程中刷新目录和字段，输出新 DOCX 与 PDF，失败不发布半成品。"""
    roots = _roots(base_dir, additional_dirs)
    source = _resolve(path, roots)
    if source.suffix.lower() != ".docx":
        raise ValueError("目录刷新只支持 .docx 文件")
    directory = _resolve(output_dir, roots, exists=False)
    docx_path = _resolve(directory / f"{source.stem}.updated.docx", roots, exists=False)
    pdf_path = _resolve(directory / f"{source.stem}.pdf", roots, exists=False)
    for output in (docx_path, pdf_path):
        _new_output(output, source)
    expected_tocs = _source_toc_count(source)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".office-", dir=directory) as temporary:
        work = Path(temporary)
        staged_docx, staged_pdf = work / "updated.docx", work / "rendered.pdf"
        result = _run_office(source, staged_docx, staged_pdf, work)
        if (result.get("fieldsUpdated") is not True
                or result.get("indexCount", -1) != result.get("indexesUpdated")
                or result.get("tocCount", -1) < expected_tocs):
            raise RuntimeError("Office 未确认完成字段及全部目录刷新，未发布输出文件")
        if not all(p.is_file() and p.stat().st_size > 0 for p in (staged_docx, staged_pdf)):
            raise RuntimeError("Office 未生成完整的 DOCX 与 PDF")
        _publish_files([(staged_docx, docx_path), (staged_pdf, pdf_path)])
    return {**result, "docxPath": str(docx_path), "pdfPath": str(pdf_path),
            "sourcePath": str(source), "tocStatus": "updated" if result["tocCount"] else "not_present"}


def _run_script(executable: str, script: str, arguments: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [executable, "-c", script, *arguments], capture_output=True,
            encoding="utf-8", errors="replace", timeout=180, check=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Office 刷新及渲染超时") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Office 刷新及渲染失败：{error.stderr[-2000:]}") from error
    return json.loads(completed.stdout)


def _run_office(source: Path, docx_path: Path, pdf_path: Path, work: Path) -> dict[str, Any]:
    soffice = os.environ.get("CCSDK_LIBREOFFICE_PATH") or shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        if os.name == "nt":
            return _run_script(sys.executable, _WPS_SCRIPT, [str(source), str(docx_path), str(pdf_path)])
        raise RuntimeError("未找到 LibreOffice；安装 libreoffice-writer 与 python3-uno 后重试")
    pipe = "scribe_" + uuid.uuid4().hex
    profile = work / "lo-profile"
    # 每次调用隔离用户配置与 UNO 管道，避免接入已有桌面实例或并发串用文档。
    process = subprocess.Popen([
        soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo",
        "--nodefault", "--nofirststartwizard", "--norestore",
        f"--accept=pipe,name={pipe};urp;StarOffice.ComponentContext",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        interpreter = os.environ.get("CCSDK_UNO_PYTHON") or (sys.executable if os.name == "nt" else "/usr/bin/python3")
        return _run_script(interpreter, _UNO_SCRIPT, [pipe, str(source), str(docx_path), str(pdf_path)])
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


_UNO_SCRIPT = r'''
import json, sys, time
import uno
from com.sun.star.beans import PropertyValue

def properties(**values):
    result = []
    for name, value in values.items():
        item = PropertyValue()
        item.Name, item.Value = name, value
        result.append(item)
    return tuple(result)

local = uno.getComponentContext()
resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
deadline = time.monotonic() + 30
while True:
    try:
        context = resolver.resolve("uno:pipe,name=" + sys.argv[1] + ";urp;StarOffice.ComponentContext")
        break
    except Exception:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.2)
desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
document = desktop.loadComponentFromURL(uno.systemPathToFileUrl(sys.argv[2]), "_blank", 0,
    properties(Hidden=True, ReadOnly=True, MacroExecutionMode=0, UpdateDocMode=0))
if document is None:
    raise RuntimeError("LibreOffice could not open the document")
try:
    indexes = document.getDocumentIndexes()
    count = indexes.getCount()
    toc_count = sum(indexes.getByIndex(i).supportsService("com.sun.star.text.ContentIndex") for i in range(count))
    for _ in range(2):
        document.refresh()
        document.getTextFields().refresh()
        for i in range(count):
            indexes.getByIndex(i).update()
    document.storeToURL(uno.systemPathToFileUrl(sys.argv[3]), properties(FilterName="Office Open XML Text", Overwrite=False))
    document.storeToURL(uno.systemPathToFileUrl(sys.argv[4]), properties(FilterName="writer_pdf_Export", Overwrite=False))
    print(json.dumps({"engine":"libreoffice-uno", "indexCount":count, "tocCount":toc_count,
        "indexesUpdated":count, "fieldsUpdated":True}))
finally:
    document.close(True)
'''


_WPS_SCRIPT = r'''
import json, sys
import pythoncom
from win32com.client import DispatchEx

pythoncom.CoInitialize()
office = None
try:
    office = DispatchEx("KWPS.Application")
    office.Visible = False
    office.DisplayAlerts = 0
    office.AutomationSecurity = 3
    document = office.Documents.Open(sys.argv[1], False, True)
    try:
        collections = [document.TablesOfContents, document.TablesOfFigures, document.Indexes]
        counts = [collection.Count for collection in collections]
        for _ in range(2):
            document.Repaginate()
            failed = document.Fields.Update()
            if failed not in (None, 0):
                raise RuntimeError("WPS could not update field " + str(failed))
            for collection, count in zip(collections, counts):
                for index in range(1, count + 1):
                    collection.Item(index).Update()
        document.Repaginate()
        document.SaveAs(sys.argv[2], 12)
        document.ExportAsFixedFormat(sys.argv[3], 17)
        print(json.dumps({"engine":"wps-com", "indexCount":sum(counts), "tocCount":counts[0],
            "indexesUpdated":sum(counts), "fieldsUpdated":True}))
    finally:
        document.Close(0)
finally:
    if office is not None:
        office.Quit()
    pythoncom.CoUninitialize()
'''


def read_pdf(path, base_dir, additional_dirs=None, start=1, limit=5, render=False, output_dir=None) -> dict[str, Any]:
    """从 1 起分页读取 PDF，可将所选页面渲染为 PNG；每次最多读取 20 页。"""
    if type(start) is not int or type(limit) is not int or start < 1 or not 1 <= limit <= 20:
        raise ValueError("start 必须为正整数，limit 必须介于 1 至 20")
    roots = _roots(base_dir, additional_dirs)
    source = _resolve(path, roots)
    if source.suffix.lower() != ".pdf":
        raise ValueError("分页阅读只支持 .pdf 文件")
    directory = _resolve(output_dir or source.parent / f"{source.stem}.pages", roots, exists=False) if render else None
    # PDFium 不支持多线程同时调用；MCP 的 to_thread 入口共享此进程级锁。
    with _PDFIUM_LOCK:
        return _read_pdf_pages(source, roots, directory, start, limit)


def _read_pdf_pages(source: Path, roots: list[Path], directory: Path | None, start: int, limit: int) -> dict[str, Any]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(source)
    try:
        count = len(document)
        if start > count:
            raise ValueError(f"start 超过 PDF 总页数 {count}")
        stop = min(count, start + limit - 1)
        if directory is not None:
            for number in range(start, stop + 1):
                _new_output(_resolve(directory / f"page-{number:04}.png", roots, exists=False), source)
            directory.mkdir(parents=True, exist_ok=True)
        pages = []
        for number in range(start, stop + 1):
            page = document[number - 1]
            try:
                textpage = page.get_textpage()
                try:
                    item = {"page": number, "text": textpage.get_text_bounded(),
                            "width": page.get_width(), "height": page.get_height()}
                finally:
                    textpage.close()
                if directory is not None:
                    target = directory / f"page-{number:04}.png"
                    bitmap = page.render(scale=1.5)
                    try:
                        image = bitmap.to_pil()
                        try:
                            with target.open("xb") as output:
                                image.save(output, format="PNG")
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                    item["imagePath"] = str(target)
                pages.append(item)
            finally:
                page.close()
        return {"path": str(source), "pageCount": count, "start": start, "pages": pages,
                "nextStart": stop + 1 if stop < count else None, "engine": "pdfium"}
    finally:
        document.close()
