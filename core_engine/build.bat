@echo off
setlocal
cd /d "%~dp0"
g++ -std=c++17 -O2 -static -shared -DBUILDING_TRACKSUM pareto_dijkstra.cpp bridge.cpp -o tracksum_engine.dll
if errorlevel 1 (
  echo Gagal membangun tracksum_engine.dll
  exit /b 1
)
echo Berhasil membangun tracksum_engine.dll
