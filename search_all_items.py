# -*- coding: utf-8 -*-
"""
Procedure/Function 검색 스크립트 (개선 버전)
- Java 및 XML 파일에서 Procedure/Function 사용 현황 검색
- 검색 결과를 CSV 파일로 출력
"""

__version__ = "1.3.0"
__author__ = "newbigwater@gmail.com"
__date__ = "2026-01-09"
__description__ = "Procedure/Function 검색 및 리포트 생성 도구 (라인 번호 추적 + 프로그레스바 + 주석 필터링)"

import csv
import re
import pathlib
import json
import logging
from typing import List, Dict, Set
from dataclasses import dataclass
import sys
import argparse
import time


@dataclass
class SearchConfig:
    """검색 설정 클래스"""
    base_path: pathlib.Path
    input_file: pathlib.Path
    java_output: pathlib.Path
    xml_output: pathlib.Path
    input_encoding: str
    output_encoding: str
    xml_filters: List[str]
    skip_patterns: List[str]


class ProgressBar:
    """순수 Python 프로그레스바 (npm 스타일)"""
    
    def __init__(self, total: int, desc: str = "진행 중", bar_length: int = 25):
        """
        Args:
            total: 전체 작업 수
            desc: 작업 설명
            bar_length: 프로그레스바 길이 (문자 수)
        """
        self.total = total
        self.desc = desc
        self.bar_length = bar_length
        self.current = 0
        self.start_time = time.time()
        self.last_update = 0
    
    def update(self, n: int = 1, item_name: str = ""):
        """
        프로그레스바 업데이트
        
        Args:
            n: 증가량
            item_name: 현재 처리 중인 항목명 (선택)
        """
        self.current += n
        current_time = time.time()
        
        # 1초에 한 번만 업데이트 (깜빡임 방지)
        if current_time - self.last_update < 0.5 and self.current < self.total:
            return
        
        self.last_update = current_time
        self._render(item_name)
    
    def _render(self, item_name: str = ""):
        """프로그레스바 렌더링"""
        # 진행률 계산
        progress = self.current / self.total
        percent = progress * 100
        
        # 프로그레스바 생성
        filled = int(self.bar_length * progress)
        bar = '█' * filled + '░' * (self.bar_length - filled)
        
        # 경과 시간 계산
        elapsed = time.time() - self.start_time
        elapsed_str = self._format_time(elapsed)
        
        # 예상 남은 시간 계산
        if self.current > 0:
            eta = elapsed * (self.total - self.current) / self.current
            eta_str = self._format_time(eta)
        else:
            eta_str = "--:--"
        
        # 항목명 표시 (짧게)
        item_display = ""
        if item_name:
            max_len = 30
            if len(item_name) > max_len:
                item_display = f" | {item_name[:max_len-3]}..."
            else:
                item_display = f" | {item_name}"
        
        # 출력 (한 줄로)
        output = f"\r{self.desc}: [{bar}] {self.current}/{self.total} ({percent:.1f}%) | {elapsed_str} 경과, {eta_str} 남음{item_display}"
        
        # 터미널 너비 제한 (120자)
        if len(output) > 120:
            output = output[:117] + "..."
        
        # 출력 (줄바꿈 없음)
        sys.stdout.write(output)
        sys.stdout.flush()
        
        # 완료 시 줄바꿈
        if self.current >= self.total:
            sys.stdout.write("\n")
            sys.stdout.flush()
    
    def _format_time(self, seconds: float) -> str:
        """시간 포맷팅 (mm:ss)"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
    
    def close(self):
        """프로그레스바 종료 (완료 표시)"""
        if self.current < self.total:
            self.current = self.total
            self._render()


class ConfigManager:
    """설정 관리 클래스"""
    
    @staticmethod
    def load_config(config_path: str = 'config.json') -> SearchConfig:
        """설정 파일 로드"""
        try:
            # 설정 파일 읽기
            config_file = pathlib.Path(config_path)
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                logging.warning(f"설정 파일 {config_path}를 찾을 수 없습니다. 기본 설정을 사용합니다.")
                config = {}
            
            # 기본 경로 설정
            base_path = pathlib.Path(config.get('base_path', '.')).resolve()
            
            # 경로가 존재하지 않으면 스크립트 위치 사용
            if not base_path.exists() or base_path == pathlib.Path('.').resolve():
                base_path = pathlib.Path(__file__).parent.resolve()
            
            return SearchConfig(
                base_path=base_path,
                input_file=base_path / config.get('input_file', 'Item List.csv'),
                java_output=base_path / config.get('output_files', {}).get('java', 'java.csv'),
                xml_output=base_path / config.get('output_files', {}).get('xml', 'SqlXml.csv'),
                input_encoding=config.get('encoding', {}).get('input', 'cp949'),
                output_encoding=config.get('encoding', {}).get('output', 'utf-8-sig'),
                xml_filters=config.get('search_patterns', {}).get('xml_file_filter', ['sql', 'mssql']),
                skip_patterns=config.get('search_patterns', {}).get('skip_lines', ['#', '"243', '"244'])
            )
        except Exception as e:
            logging.error(f"설정 파일 로드 중 오류: {e}")
            raise
    
    @staticmethod
    def validate_config(config: SearchConfig) -> bool:
        """
        설정 유효성 검증
        
        Args:
            config: 검증할 설정
            
        Returns:
            유효하면 True, 아니면 False
        """
        is_valid = True
        
        # 기본 경로 확인
        if not config.base_path.exists():
            logging.error(f"기본 경로가 존재하지 않습니다: {config.base_path}")
            is_valid = False
        elif not config.base_path.is_dir():
            logging.error(f"유효하지 않은 경로입니다 (디렉토리가 아님): {config.base_path}")
            is_valid = False
        
        # 입력 파일 확인
        if not config.input_file.exists():
            logging.error(f"입력 파일이 없습니다: {config.input_file}")
            is_valid = False
        elif not config.input_file.is_file():
            logging.error(f"유효하지 않은 입력 파일입니다: {config.input_file}")
            is_valid = False
        
        # 출력 디렉토리 확인 (파일이 생성될 디렉토리)
        java_output_dir = config.java_output.parent
        if not java_output_dir.exists():
            logging.warning(f"출력 디렉토리가 없습니다. 생성합니다: {java_output_dir}")
            try:
                java_output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logging.error(f"출력 디렉토리 생성 실패: {e}")
                is_valid = False
        
        if is_valid:
            logging.info("설정 검증 완료")
        else:
            logging.error("설정 검증 실패")
        
        return is_valid


class PatternMatcher:
    """정규식 패턴 매칭 클래스 (성능 최적화)"""
    
    def __init__(self, item_name: str):
        """
        패턴 매처 초기화
        
        Args:
            item_name: 검색할 항목명
        """
        self.item_name = item_name
        self.item_lower = item_name.lower()
        
        # 정규식 패턴 사전 컴파일 (성능 최적화)
        self.exact_pattern = re.compile(r'\b' + re.escape(item_name) + r'\b', re.IGNORECASE)
        self.partial_pattern = re.compile(re.escape(item_name), re.IGNORECASE)
        
        # Java 패턴
        self.class_pattern = re.compile(r'\bclass\s+(\w+)', re.IGNORECASE)
        self.method_pattern = re.compile(
            r'(?:public|protected|private|static|final|synchronized|abstract|\s)+[\w\<\>\[\]]+\s+(\w+)\s*\([^;]*\)\s*\{?',
            re.IGNORECASE
        )
        
        # XML 패턴 (하이픈 포함 이름 지원) - 통합 최적화
        # dbo.FN_XXX 또는 SCRIF.dbo.FN_XXX 패턴 통합
        self.db_func_pattern = re.compile(
            r'\b(?:SCRIF\.)?dbo\.([\w-]+)\s*\(',
            re.IGNORECASE
        )
        
        # CALL/EXEC 패턴 통합: EXEC SP_XXX, EXEC dbo.SP_XXX, EXEC SCRIF.dbo.SP_XXX
        self.db_proc_pattern = re.compile(
            r'\b(CALL|EXEC)\s+(?:(?:SCRIF\.)?dbo\.)?([\w-]+)',
            re.IGNORECASE
        )
        
        # XML id 속성 패턴
        self.xml_id_pattern = re.compile(
            r'id\s*=\s*["\'][^"\']*' + re.escape(item_name) + r'[^"\']*["\']',
            re.IGNORECASE
        )
    
    def is_match(self, line: str) -> bool:
        """
        라인이 검색 패턴과 일치하는지 확인
        
        Args:
            line: 검색할 라인
            
        Returns:
            일치 여부
        """
        line_lower = line.lower()
        
        # 빠른 체크: 항목명이 포함되어 있지 않으면 바로 False
        if self.item_lower not in line_lower:
            return False
        
        # 정확한 매칭 또는 부분 일치 확인
        return self.exact_pattern.search(line) is not None or \
               self.partial_pattern.search(line) is not None


class ItemListReader:
    """Item List 읽기 클래스"""
    
    @staticmethod
    def read(file_path: pathlib.Path, encoding: str, skip_patterns: List[str]) -> List[str]:
        """
        Item List 파일 읽기
        
        Args:
            file_path: 파일 경로
            encoding: 인코딩
            skip_patterns: 스킵할 패턴 목록
            
        Returns:
            항목 목록
        """
        items = []
        
        try:
            with file_path.open('r', encoding=encoding, errors='ignore') as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    
                    # 첫 번째 열 가져오기
                    item = row[0].strip().strip('"')
                    
                    # 스킩 패턴 확인
                    if any(item.startswith(pattern) for pattern in skip_patterns):
                        continue
                    
                    # 유효한 항목명인지 확인 (영문, 숫자, 언더스코어만)
                    if item and re.match(r'^[A-Za-z0-9_]+$', item):
                        items.append(item)
            
            logging.info(f"총 {len(items)}개 항목 발견")
            return items
            
        except FileNotFoundError:
            logging.error(f"파일을 찾을 수 없습니다: {file_path}")
            raise
        except PermissionError:
            logging.error(f"파일 접근 권한이 없습니다: {file_path}")
            raise
        except Exception as e:
            logging.error(f"Item List 읽기 중 오류: {e}")
            raise


class CommentDetector:
    """주석 감지 클래스"""
    
    @staticmethod
    def is_comment_line_java(line: str, in_block_comment: bool) -> tuple:
        """
        Java/C# 주석 라인 감지
        
        Args:
            line: 검사할 라인
            in_block_comment: 현재 블록 주석 내부인지 여부
            
        Returns:
            (is_comment, in_block_comment) 튜플
        """
        stripped = line.strip()
        
        # 블록 주석 내부인 경우
        if in_block_comment:
            # 블록 주석 종료 확인
            if '*/' in stripped:
                in_block_comment = False
            return (True, in_block_comment)
        
        # 한 줄 주석
        if stripped.startswith('//'):
            return (True, False)
        
        # 블록 주석 시작
        if stripped.startswith('/*') or stripped.startswith('/**'):
            # 같은 줄에 끝나는 경우
            if '*/' in stripped:
                return (True, False)
            else:
                return (True, True)
        
        # 코드 중간에 주석이 있는 경우 처리
        # 예: String query = "test"; // 주석
        if '//' in stripped:
            # '//' 이전에 실제 코드가 있는지 확인
            before_comment = stripped.split('//')[0].strip()
            if before_comment:
                # 코드가 있으면 주석 아님
                return (False, False)
            else:
                return (True, False)
        
        return (False, False)
    
    @staticmethod
    def is_comment_line_xml(line: str, in_block_comment: bool) -> tuple:
        """
        XML 주석 라인 감지
        
        Args:
            line: 검사할 라인
            in_block_comment: 현재 블록 주석 내부인지 여부
            
        Returns:
            (is_comment, in_block_comment) 튜플
        """
        stripped = line.strip()
        
        # 블록 주석 내부인 경우
        if in_block_comment:
            # 블록 주석 종료 확인
            if '-->' in stripped:
                in_block_comment = False
            return (True, in_block_comment)
        
        # 블록 주석 시작
        if '<!--' in stripped:
            # 같은 줄에 끝나는 경우
            if '-->' in stripped:
                return (True, False)
            else:
                return (True, True)
        
        return (False, False)
    
    @staticmethod
    def mark_comment_lines_java(lines: List[str]) -> List[bool]:
        """
        Java 파일의 모든 주석 라인 표시
        
        Args:
            lines: 파일의 모든 라인
            
        Returns:
            주석 여부 리스트 (True: 주석, False: 코드)
        """
        is_comment_list = []
        in_block = False
        
        for line in lines:
            is_comment, in_block = CommentDetector.is_comment_line_java(line, in_block)
            is_comment_list.append(is_comment)
        
        return is_comment_list
    
    @staticmethod
    def mark_comment_lines_xml(lines: List[str]) -> List[bool]:
        """
        XML 파일의 모든 주석 라인 표시
        
        Args:
            lines: 파일의 모든 라인
            
        Returns:
            주석 여부 리스트 (True: 주석, False: 코드)
        """
        is_comment_list = []
        in_block = False
        
        for line in lines:
            is_comment, in_block = CommentDetector.is_comment_line_xml(line, in_block)
            is_comment_list.append(is_comment)
        
        return is_comment_list


class JavaSearcher:
    """Java 파일 검색 클래스"""
    
    def __init__(self, base_path: pathlib.Path):
        self.base_path = base_path
    
    def search(self, item_name: str) -> List[Dict]:
        """
        Java 파일에서 항목 검색
        
        Args:
            item_name: 검색할 항목명
            
        Returns:
            검색 결과 리스트
        """
        results = []
        matcher = PatternMatcher(item_name)
        
        for java_file in self.base_path.rglob('*.java'):
            try:
                content = java_file.read_text(encoding='utf-8', errors='ignore')
                lines = content.splitlines()
                
                # 주석 라인 표시
                comment_marks = CommentDetector.mark_comment_lines_java(lines)
                
                for i, line in enumerate(lines, 1):
                    # 주석 라인은 스킵
                    if comment_marks[i - 1]:
                        continue
                    
                    if not matcher.is_match(line):
                        continue
                    
                    # 클래스명 추출 (최대 50줄 이전까지)
                    class_name = self._extract_class_name(lines, i, matcher)
                    
                    # 메서드명 추출 (최대 20줄 이전까지)
                    method_name = self._extract_method_name(lines, i, matcher)
                    
                    rel_path = str(java_file.relative_to(self.base_path)).replace('\\', '/')
                    
                    results.append({
                        'item': item_name,
                        'file': rel_path,
                        'class': class_name,
                        'method': method_name,
                        'line_number': i,
                        'line': line.strip()
                    })
                    
            except UnicodeDecodeError:
                logging.warning(f"파일 인코딩 오류 (스킵): {java_file}")
            except PermissionError:
                logging.warning(f"파일 접근 권한 없음 (스킵): {java_file}")
            except Exception as e:
                logging.warning(f"파일 처리 중 오류 (스킵): {java_file} - {e}")
        
        return results
    
    def _extract_class_name(self, lines: List[str], current_line: int, matcher: PatternMatcher) -> str:
        """클래스명 추출"""
        for j in range(max(0, current_line - 50), current_line):
            if j >= len(lines):
                break
            match = matcher.class_pattern.search(lines[j])
            if match:
                return match.group(1)
        return ''
    
    def _extract_method_name(self, lines: List[str], current_line: int, matcher: PatternMatcher) -> str:
        """메서드명 추출"""
        for j in range(max(0, current_line - 20), current_line):
            if j >= len(lines):
                break
            match = matcher.method_pattern.search(lines[j])
            if match:
                return match.group(1)
        return ''


class XmlSearcher:
    """XML 파일 검색 클래스"""
    
    def __init__(self, base_path: pathlib.Path, xml_filters: List[str]):
        self.base_path = base_path
        self.xml_filters = xml_filters
    
    def search(self, item_name: str) -> List[Dict]:
        """
        XML 파일에서 항목 검색
        
        Args:
            item_name: 검색할 항목명
            
        Returns:
            검색 결과 리스트
        """
        results = []
        matcher = PatternMatcher(item_name)
        
        for xml_file in self.base_path.rglob('*.xml'):
            # SQL 관련 XML만 검색
            if not self._is_sql_related(xml_file):
                continue
            
            try:
                content = xml_file.read_text(encoding='utf-8', errors='ignore')
                lines = content.splitlines()
                
                # 주석 라인 표시
                comment_marks = CommentDetector.mark_comment_lines_xml(lines)
                
                for i, line in enumerate(lines, 1):
                    # 주석 라인은 스킵
                    if comment_marks[i - 1]:
                        continue
                    
                    line_lower = line.lower()
                    
                    # 빠른 체크
                    if matcher.item_lower not in line_lower:
                        continue
                    
                    matched, proc_name, func_name = self._analyze_line(line, item_name, matcher)
                    
                    if matched:
                        rel_path = str(xml_file.relative_to(self.base_path)).replace('\\', '/')
                        
                        results.append({
                            'item': item_name,
                            'file': rel_path,
                            'procedure': proc_name,
                            'function': func_name,
                            'line_number': i,
                            'line': line.strip()
                        })
                        
            except UnicodeDecodeError:
                logging.warning(f"파일 인코딩 오류 (스킵): {xml_file}")
            except PermissionError:
                logging.warning(f"파일 접근 권한 없음 (스킵): {xml_file}")
            except Exception as e:
                logging.warning(f"파일 처리 중 오류 (스킵): {xml_file} - {e}")
        
        return results
    
    def _is_sql_related(self, xml_file: pathlib.Path) -> bool:
        """SQL 관련 XML 파일인지 확인"""
        file_path_lower = str(xml_file).lower()
        return any(filter_word in file_path_lower for filter_word in self.xml_filters)
    
    def _analyze_line(self, line: str, item_name: str, matcher: PatternMatcher) -> tuple:
        """
        라인 분석 및 프로시저/함수명 추출
        
        Returns:
            (matched, proc_name, func_name) 튜플
        """
        matched = False
        proc_name = ''
        func_name = ''
        
        # 정확한 매칭 확인
        if matcher.exact_pattern.search(line):
            matched = True
        
        # 함수 호출 패턴 (dbo.FN_XXX 또는 SCRIF.dbo.FN_XXX) - 통합 패턴 사용
        func_match = matcher.db_func_pattern.search(line)
        if func_match:
            extracted_func = func_match.group(1)
            if matcher.item_lower in extracted_func.lower():
                func_name = extracted_func
                matched = True
        
        # 프로시저 호출 패턴 (CALL/EXEC) - 통합 패턴 사용
        proc_match = matcher.db_proc_pattern.search(line)
        if proc_match:
            # 통합 패턴의 마지막 그룹이 프로시저명
            extracted_proc = proc_match.group(2)
            if matcher.item_lower in extracted_proc.lower():
                proc_name = extracted_proc
                matched = True
        
        # XML id 속성 검색
        if not matched and matcher.xml_id_pattern.search(line):
            matched = True
        
        # 함수명/프로시저명이 추출되지 않았으면 항목명으로 설정
        if matched and not proc_name and not func_name:
            if item_name.startswith(('SP_', 'IF_', 'USP_')):
                proc_name = item_name
            elif item_name.startswith('FN_'):
                func_name = item_name
        
        return matched, proc_name, func_name


class ReportWriter:
    """리포트 작성 클래스"""
    
    @staticmethod
    def write_java_report(file_path: pathlib.Path, results: List[Dict], encoding: str):
        """Java 검색 결과 리포트 작성"""
        try:
            with file_path.open('w', encoding=encoding, newline='', errors='replace') as f:
                writer = csv.writer(f)
                writer.writerow(['Procedure/Function name', '파일 경로', '클래스', '메서드', '호출한 라인 번호', '호출한 라인 텍스트'])
                
                seen: Set[tuple] = set()
                for r in results:
                    key = (r['item'], r['file'], r['class'], r['method'], r['line_number'], r['line'])
                    if key not in seen:
                        seen.add(key)
                        clean_line = ReportWriter._clean_line(r['line'])
                        writer.writerow([r['item'], r['file'], r['class'], r['method'], r['line_number'], f'"{clean_line}"'])
            
            logging.info(f"java.csv 작성 완료: {len(seen)}개 항목")
            
        except PermissionError:
            logging.error(f"파일 쓰기 권한 없음: {file_path}")
            raise
        except Exception as e:
            logging.error(f"Report2 작성 중 오류: {e}")
            raise
    
    @staticmethod
    def write_xml_report(file_path: pathlib.Path, results: List[Dict], encoding: str):
        """XML 검색 결과 리포트 작성"""
        try:
            with file_path.open('w', encoding=encoding, newline='', errors='replace') as f:
                writer = csv.writer(f)
                writer.writerow(['Procedure/Function name', '파일 경로', '프로시저명', '함수명', '호출한 라인 번호', '호출한 라인 텍스트'])
                
                seen: Set[tuple] = set()
                for r in results:
                    key = (r['item'], r['file'], r['procedure'], r['function'], r['line_number'], r['line'])
                    if key not in seen:
                        seen.add(key)
                        clean_line = ReportWriter._clean_line(r['line'])
                        writer.writerow([r['item'], r['file'], r['procedure'], r['function'], r['line_number'], f'"{clean_line}"'])
            
            logging.info(f"SqlXml.csv 작성 완료: {len(seen)}개 항목")
            
        except PermissionError:
            logging.error(f"파일 쓰기 권한 없음: {file_path}")
            raise
        except Exception as e:
            logging.error(f"Report3 작성 중 오류: {e}")
            raise
    
    @staticmethod
    def _clean_line(line: str) -> str:
        """인코딩 불가능한 문자 제거 (버그 수정: .remove() → .replace())"""
        return line.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').strip()
    
    @staticmethod
    def print_statistics(java_results: List[Dict], xml_results: List[Dict]):
        """
        검색 결과 통계 출력
        
        Args:
            java_results: Java 검색 결과 리스트
            xml_results: XML 검색 결과 리스트
        """
        print("\n" + "=" * 60)
        print("검색 결과 통계")
        print("=" * 60)
        
        # Java 검색 통계
        print("\n[Java 검색]")
        print(f"  - 총 항목: {len(java_results)}개")
        if java_results:
            unique_files = len(set(r['file'] for r in java_results))
            unique_classes = len(set(r['class'] for r in java_results if r['class']))
            unique_methods = len(set(r['method'] for r in java_results if r['method']))
            print(f"  - 파일: {unique_files}개")
            print(f"  - 클래스: {unique_classes}개")
            print(f"  - 메서드: {unique_methods}개")
        
        # XML 검색 통계
        print("\n[XML 검색]")
        print(f"  - 총 항목: {len(xml_results)}개")
        if xml_results:
            unique_files = len(set(r['file'] for r in xml_results))
            function_count = len([r for r in xml_results if r.get('function')])
            procedure_count = len([r for r in xml_results if r.get('procedure')])
            print(f"  - 파일: {unique_files}개")
            print(f"  - 함수: {function_count}개")
            print(f"  - 프로시저: {procedure_count}개")
        
        # 전체 통계
        total = len(java_results) + len(xml_results)
        print(f"\n[전체 통계]")
        print(f"  - 총 검색 결과: {total}개")
        if total > 0:
            java_ratio = (len(java_results) / total) * 100
            xml_ratio = (len(xml_results) / total) * 100
            print(f"  - Java 비율: {java_ratio:.1f}%")
            print(f"  - XML 비율: {xml_ratio:.1f}%")
        
        print("=" * 60)


def setup_logging(log_file: str = None):
    """
    로깅 설정
    
    Args:
        log_file: 로그 파일 경로 (선택사항, 없으면 콘솔 출력만)
    """
    handlers = [logging.StreamHandler(sys.stdout)]
    
    # 로그 파일이 지정된 경우 파일 핸들러 추가
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            handlers.append(file_handler)
        except Exception as e:
            print(f"[경고] 로그 파일 생성 실패: {e}")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


def main():
    """메인 함수"""
    # 명령줄 인자 파싱
    parser = argparse.ArgumentParser(description='Procedure/Function 검색 도구')
    parser.add_argument('--log-file', type=str, help='로그 파일 경로 (선택사항)')
    args = parser.parse_args()
    
    # 로깅 초기화 (로그 파일명 전달)
    setup_logging(args.log_file)
    
    try:
        # 버전 정보 출력
        logging.info(f"search_all_items v{__version__}")
        logging.info(f"Author: {__author__}")
        logging.info(f"Date: {__date__}")
        if args.log_file:
            logging.info(f"Log file: {args.log_file}")
        
        # 설정 로드
        logging.info("\n설정 로드 중...")
        config = ConfigManager.load_config()
        
        logging.info(f"작업 디렉토리: {config.base_path}")
        logging.info(f"Item List 파일: {config.input_file}")
        
        # 설정 검증
        logging.info("\n설정 검증 중...")
        if not ConfigManager.validate_config(config):
            logging.error("설정 검증 실패. 프로그램을 종료합니다.")
            sys.exit(1)
        
        # Item List 읽기
        logging.info("Item List 읽는 중...")
        items = ItemListReader.read(config.input_file, config.input_encoding, config.skip_patterns)
        
        if not items:
            logging.warning("검색할 항목이 없습니다.")
            sys.exit(0)
        
        # 검색 시작
        logging.info(f"\n검색 시작... (총 {len(items)}개 항목)")
        java_searcher = JavaSearcher(config.base_path)
        xml_searcher = XmlSearcher(config.base_path, config.xml_filters)
        
        java_results = []
        xml_results = []
        
        # 프로그레스바 생성
        progress_bar = ProgressBar(total=len(items), desc="Item 검색 중", bar_length=25)
        
        for idx, item in enumerate(items, 1):
            # 검색 수행
            java_results.extend(java_searcher.search(item))
            xml_results.extend(xml_searcher.search(item))
            
            # 프로그레스바 업데이트
            progress_bar.update(n=1, item_name=item)
        
        # 프로그레스바 종료
        progress_bar.close()
        
        logging.info(f"\n검색 완료!")
        logging.info(f"Java 결과: {len(java_results)}개")
        logging.info(f"XML 결과: {len(xml_results)}개")
        
        # 통계 정보 출력
        ReportWriter.print_statistics(java_results, xml_results)
        
        # 리포트 작성
        logging.info("\njava.csv 작성 중...")
        ReportWriter.write_java_report(config.java_output, java_results, config.output_encoding)
        
        logging.info("\nSqlXml.csv 작성 중...")
        ReportWriter.write_xml_report(config.xml_output, xml_results, config.output_encoding)
        
        logging.info("\n완료!")
        
    except KeyboardInterrupt:
        logging.warning("\n사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"\n실행 중 오류 발생: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
