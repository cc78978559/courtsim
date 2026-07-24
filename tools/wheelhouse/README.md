# Local wheelhouse

本目录用于保存当前 Windows / CPython 3.13 开发工具的离线安装包。

`.whl` 文件有意不纳入 Git。运行 `tools.ps1 bootstrap` 时，如果本目录存在安装包，就使用 `--no-index` 完全离线安装；否则才访问包索引。

需要刷新时，在联网环境运行：

```powershell
.\.venv\Scripts\python.exe -m pip download --dest tools\wheelhouse -r requirements\dev.lock
.\.venv\Scripts\python.exe -m pip download --dest tools\wheelhouse -r requirements\build.lock
```

