# Perception Layer

Simulated ambient IoT tag layer.

## Local setup (Windows)

Run from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\bootstrap.ps1
```

If `python` resolves to the Microsoft Store alias, pass an explicit interpreter path:

```powershell
.\scripts\bootstrap.ps1 -Python "C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe"
```