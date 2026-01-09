@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

REM ============================================
REM Procedure/Function 검색 스크립트 실행
REM ============================================

REM 배치 파일이 있는 디렉토리로 이동
cd /d "%~dp0"

REM 로그 파일명 설정 (타임스탬프 포함)
set LOG_FILE=search_log_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%.txt
set LOG_FILE=%LOG_FILE: =0%

REM Python 설치 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않거나 PATH에 등록되지 않았습니다.
    echo Python을 설치하거나 PATH 환경변수를 확인해주세요.
    pause
    exit /b 1
)

REM 실행 시작 메시지
echo ============================================
echo Procedure/Function 검색 시작
echo ============================================
echo 실행 시간: %date% %time%
echo 작업 디렉토리: %CD%
echo 로그 파일: %LOG_FILE%
echo.

REM Python 스크립트 실행 (로그 파일명 전달)
python search_all_items.py --log-file "%LOG_FILE%"

REM 실행 결과 확인
if errorlevel 1 (
    echo.
    echo [오류] 스크립트 실행 중 오류가 발생했습니다.
    echo 오류 코드: %errorlevel%
    pause
    exit /b %errorlevel%
)

echo.
echo ============================================
echo 검색 완료!
echo ============================================
echo.
echo 생성된 파일:
if exist "Java.csv" (
    echo   - Java.csv ^(Java 검색 결과^)
)
if exist "SqlXml.csv" (
    echo   - SqlXml.csv ^(XML 검색 결과^)
)
echo.

REM 오검색 항목 정리
echo ============================================
echo 오검색 항목 정리 시작
echo ============================================
echo.

REM 정리할 파일 확인
set CLEAN_REPORT2=0
set CLEAN_REPORT3=0

if exist "Java.csv" (
    set CLEAN_REPORT2=1
)
if exist "SqlXml.csv" (
    set CLEAN_REPORT3=1
)

if !CLEAN_REPORT2!==0 if !CLEAN_REPORT3!==0 (
    echo [정보] 정리할 리포트 파일이 없습니다.
    goto :skip_clean
)

REM 오검색 정리 스크립트 실행
python clean_reports.py

if errorlevel 1 (
    echo.
    echo [경고] 오검색 정리 중 오류가 발생했습니다.
    echo 오류 코드: %errorlevel%
    echo 원본 파일은 그대로 유지됩니다.
) else (
    echo.
    echo ============================================
    echo 오검색 정리 완료!
    echo ============================================
)

:skip_clean
echo.
echo ============================================
echo 전체 작업 완료!
echo 완료 시간: %date% %time%
echo ============================================
echo.
echo 생성된 로그 파일: %LOG_FILE%
echo.

pause
