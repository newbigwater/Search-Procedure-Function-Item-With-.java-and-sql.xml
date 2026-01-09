# -*- coding: utf-8 -*-
"""
Java.csv와 SqlXml.csv에서 오검색된 항목을 제거하는 스크립트
부분 일치로 인해 잘못 검색된 항목들을 필터링합니다.

config.json 설정에 따른 파일명:
- java: Java.csv
- xml: SqlXml.csv
"""

import csv
import re
from pathlib import Path

def is_false_positive(item_name, line_text, extracted_name=None):
    """
    오검색 여부를 판단합니다.
    
    Args:
        item_name: 검색한 항목명 (예: "FN_CALGRADE")
        line_text: 검색된 라인 텍스트
        extracted_name: 추출된 함수/프로시저명 (XML의 경우)
    
    Returns:
        True: 오검색 (제거해야 함)
        False: 정상 검색 (유지)
    """
    line_lower = line_text.lower()
    item_lower = item_name.lower()
    
    # 0. XML id 속성에서 문자열 연결 패턴 먼저 확인
    # 예: id="sqlFN_GETSHIFTCODE_FN_GETWORKDAY"에서 "FN_GETSHIFTCODE"는 오검색
    xml_id_pattern = re.compile(r'id\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
    xml_id_match = xml_id_pattern.search(line_text)
    if xml_id_match:
        xml_id_value = xml_id_match.group(1)
        xml_id_lower = xml_id_value.lower()
        
        # XML id 값이 검색 항목을 포함하지만 더 긴 경우
        if item_lower in xml_id_lower and len(xml_id_lower) > len(item_lower):
            # 하이픈 예외는 제외 (예: "IF_MES_MM_GR_RCV-00001")
            if '-' in xml_id_lower and not item_lower.endswith('-'):
                base_name = xml_id_lower.split('-')[0]
                if base_name == item_lower:
                    return False  # 하이픈은 버전 번호이므로 정상 검색
            # 추출된 이름이 검색 항목과 정확히 일치하더라도, XML id가 더 길면 오검색
            return True
    
    # 1. 정확한 매칭인 경우는 유지
    exact_pattern = re.compile(r'\b' + re.escape(item_name) + r'\b', re.IGNORECASE)
    exact_match = exact_pattern.search(line_text)
    
    if extracted_name:
        extracted_lower = extracted_name.lower()
        # 추출된 이름이 검색 항목과 정확히 일치하면 유지
        if extracted_lower == item_lower:
            return False
        
        # 하이픈 예외 처리 (예: "IF_MES_MM_GR_RCV-00001")
        if '-' in extracted_lower and not item_lower.endswith('-'):
            base_name = extracted_lower.split('-')[0]
            if base_name == item_lower:
                return False  # 하이픈은 버전 번호이므로 정상 검색
        
        # 추출된 이름이 검색 항목을 포함하지만 더 길면 오검색
        if item_lower in extracted_lower and len(extracted_lower) > len(item_lower):
            return True
    
    # 2. 부분 일치인 경우, 더 긴 이름의 일부인지 확인
    # 예: "SP_SNAPSHOT"이 "SP_SNAPSHOT_DAILYMATERIALLOT"의 일부인 경우
    # 예: "FN_CALGRADE"가 "FN_CALGRADE_MAIN"의 일부인 경우
    # 예: "FN_GETSHIFTCODE"가 "sqlFN_GETSHIFTCODE_FN_GETWORKDAY"의 일부인 경우
    
    # 함수/프로시저 호출 패턴에서 추출된 이름 확인
    patterns = [
        r'\bdbo\.([A-Za-z0-9_-]+)\s*\(',
        r'\bSCRIF\.dbo\.([A-Za-z0-9_-]+)\s*\(',
        r'\b(CALL|EXEC)\s+(?:SCRIF\.dbo\.|dbo\.)?([A-Za-z0-9_-]+)',
        r'["\']([A-Za-z0-9_-]+-00001)["\']',  # XML id 패턴
        r'select\s*\(["\']([A-Za-z0-9_-]+)["\']',  # Java select 패턴
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, line_text, re.IGNORECASE)
        for match in matches:
            extracted = match.group(1) if match.lastindex >= 1 else match.group(0)
            extracted_lower = extracted.lower()
            
            # 추출된 이름이 검색 항목을 포함하지만 더 길면 오검색
            if item_lower in extracted_lower and len(extracted_lower) > len(item_lower):
                # 예외: 하이픈으로 구분된 경우 (예: "IF_MES_MM_GR_RCV-00001")
                if '-' in extracted_lower and not item_lower.endswith('-'):
                    # "IF_MES_MM_GR_RCV"가 "IF_MES_MM_GR_RCV-00001"의 일부인 경우는 유지
                    base_name = extracted_lower.split('-')[0]
                    if base_name == item_lower:
                        return False
                return True
    
    # 3. 문자열 연결 패턴 (예: "sqlFN_GETSHIFTCODE_FN_GETWORKDAY")
    # 검색 항목이 다른 이름과 연결된 경우 오검색
    # 단, 정확한 매칭이 있으면 유지
    if not exact_pattern.search(line_text):
        # 언더스코어나 대문자로 구분된 패턴 확인
        # 예: "sqlFN_GETSHIFTCODE_FN_GETWORKDAY"에서 "FN_GETSHIFTCODE"는 오검색
        word_boundary_pattern = re.compile(
            r'(?:^|[^A-Za-z0-9_])' + re.escape(item_name) + r'(?:[^A-Za-z0-9_]|$)',
            re.IGNORECASE
        )
        if not word_boundary_pattern.search(line_text):
            # 단어 경계가 없으면 오검색 가능성 높음
            return True
    
    return False

def clean_report2(input_file, output_file):
    """
    Java.csv 정리 (Java 검색 결과)
    
    표준 인코딩: UTF-8-BOM (utf-8-sig)
    표준 구분자: 쉼표 (,)
    
    하위 호환성을 위해 여러 인코딩과 구분자를 시도합니다.
    """
    cleaned_rows = []
    removed_count = 0
    
    try:
        # 표준 인코딩(UTF-8-BOM)을 우선 시도, 실패시 다른 인코딩 시도
        encodings = ['utf-8-sig', 'cp949', 'euc-kr', 'utf-8']
        delimiters = [',', '\t']
        
        rows = None
        header = None
        successful_encoding = None
        successful_delimiter = None
        
        for enc in encodings:
            for delim in delimiters:
                try:
                    with open(input_file, 'r', encoding=enc, newline='') as f:
                        reader = csv.DictReader(f, delimiter=delim)
                        rows = list(reader)
                        header = reader.fieldnames
                        
                        # 유효성 검사: 헤더가 있고 행이 있는지 확인
                        if header and len(header) > 0 and rows and len(rows) > 0:
                            # 첫 번째 행에서 필요한 컬럼 확인
                            first_row = rows[0]
                            if any('Procedure' in str(k) or 'Function' in str(k) for k in first_row.keys()):
                                successful_encoding = enc
                                successful_delimiter = delim
                                break
                except:
                    continue
            
            if successful_encoding:
                break
        
        if not header:
            print(f"  [오류] 헤더를 읽을 수 없습니다: {input_file}")
            return 0, 0
        
        if not rows or len(rows) == 0:
            print(f"  [정보] 데이터가 없습니다 (헤더만 존재)")
            return 0, 0
        
        # None 제거하고 유효한 헤더만 유지
        valid_header = [h for h in header if h is not None and str(h).strip()]
        if not valid_header:
            print(f"  [오류] 유효한 헤더가 없습니다: {header}")
            return 0, 0
        
        # 컬럼명 찾기
        item_key = None
        line_key = None
        
        for key in valid_header:
            key_str = str(key)
            if 'Procedure' in key_str or 'Function' in key_str or 'name' in key_str:
                item_key = key
            if '라인' in key_str or 'line' in key_str.lower() or '텍스트' in key_str:
                line_key = key
        
        if not item_key or not line_key:
            print(f"  [오류] 필요한 컬럼을 찾을 수 없습니다. 헤더: {valid_header}")
            return 0, 0
        
        for row in rows:
            item_name = row.get(item_key, '').strip()
            line_text = row.get(line_key, '').strip().strip('"')
            
            if not item_name:
                continue
            
            if is_false_positive(item_name, line_text):
                removed_count += 1
                continue
            
            # None 키 제거
            cleaned_row = {k: v for k, v in row.items() if k in valid_header}
            cleaned_rows.append(cleaned_row)
        
        # 정리된 데이터 저장 (원본 파일을 직접 덮어쓰기, UTF-8-BOM + 쉼표 구분자)
        with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=valid_header, delimiter=',')
            writer.writeheader()
            writer.writerows(cleaned_rows)
        
        print(f"  - 원본: {removed_count + len(cleaned_rows)}개")
        print(f"  - 제거: {removed_count}개 (오검색 항목)")
        print(f"  - 유지: {len(cleaned_rows)}개")
        
        return removed_count, len(cleaned_rows)
    except Exception as e:
        print(f"  [오류] 파일 처리 중 오류: {e}")
        return 0, 0

def clean_report3(input_file, output_file):
    """
    SqlXml.csv 정리 (XML 검색 결과)
    
    표준 인코딩: UTF-8-BOM (utf-8-sig)
    표준 구분자: 쉼표 (,)
    """
    cleaned_rows = []
    removed_count = 0
    
    try:
        with open(input_file, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            
            for row in reader:
                item_name = row.get('Procedure/Function name', '')
                line_text = row.get('호출한 라인 텍스트', '').strip('"')
                proc_name = row.get('프로시저명', '')
                func_name = row.get('함수명', '')
                
                # 추출된 이름 확인
                extracted_name = func_name if func_name else proc_name
                
                if is_false_positive(item_name, line_text, extracted_name):
                    removed_count += 1
                    continue
                
                cleaned_rows.append(row)
        
        # 정리된 데이터 저장 (원본 파일을 직접 덮어쓰기)
        with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(cleaned_rows)
        
        print(f"  - 원본: {removed_count + len(cleaned_rows)}개")
        print(f"  - 제거: {removed_count}개 (오검색 항목)")
        print(f"  - 유지: {len(cleaned_rows)}개")
        
        return removed_count, len(cleaned_rows)
    except Exception as e:
        print(f"  [오류] 파일 처리 중 오류: {e}")
        return 0, 0

if __name__ == '__main__':
    base = Path('.')
    
    # config.json 설정에 따른 파일명 사용
    java_file = base / 'Java.csv'
    xml_file = base / 'SqlXml.csv'
    
    print("=" * 50)
    print("Report 정리 시작")
    print("=" * 50)
    
    # Java 검색 결과 정리
    if java_file.exists():
        print(f"\n정리 중: {java_file.name}")
        clean_report2(java_file, java_file)
    else:
        print("\n[정보] Java.csv 파일을 찾을 수 없습니다.")
    
    # XML 검색 결과 정리
    if xml_file.exists():
        print(f"\n정리 중: {xml_file.name}")
        clean_report3(xml_file, xml_file)
    else:
        print("\n[정보] SqlXml.csv 파일을 찾을 수 없습니다.")
    
    print("\n" + "=" * 50)
    print("정리 완료!")
    print("=" * 50)
