# dart_analysis

DART 공시 분석 서비스를 위한 최소 수직 슬라이스(MVP Phase 1+) 저장소입니다.

## 현재 구현 범위
- Django 최소 프로젝트 스캐폴드
- `apps.dart_analysis` 앱
- 환경변수 `DART_API_KEY` 안전 로딩
- DART 최소 클라이언트
  - `corpCode.xml` 기반 company_name -> corp_code 해석(정확 일치만)
  - `corp_code` 기반 최근 공시 목록 최소 메타데이터 live 조회 (`list.json`)
- 입력 검증 + 초기 API 엔드포인트

## 빠른 실행

### 1) 의존성 설치
```bash
pip install -r requirements.txt
```

### 2) 환경변수 설정
```bash
export DART_API_KEY="YOUR_KEY"
```

> 보안상 실제 키 값은 로그나 응답에 노출하지 마세요.

### 3) 개발 서버 실행
```bash
python manage.py migrate
python manage.py runserver
```

## 검증 엔드포인트
- URL: `GET /api/v1/dart/validate`
- 또는: `POST /api/v1/dart/validate`

### 예시 1: company_name 기반(공식 corpCode exact 매칭 후 조회)
```bash
curl "http://127.0.0.1:8000/api/v1/dart/validate?company_name=삼성전자"
```

### 예시 2: corp_code 기반(live 공시 목록 최소 조회)
```bash
curl "http://127.0.0.1:8000/api/v1/dart/validate?corp_code=00126380"
```

### 예시 3: rcept_no 기반 원문 접근 메타데이터 조회
```bash
curl "http://127.0.0.1:8000/api/v1/dart/document?rcept_no=20260101000001"
```

## 응답 동작 요약
- `corp_code` 입력: 기존 동작 유지, 즉시 `list.json` 최소 조회
- 조회 응답은 `raw_items`(원본 최소 메타데이터), `normalized_items`(카테고리/시그널), `summary`(집계), `original_document_access`(rcept_no 기반 원문 접근 정보)로 분리 반환
- `company_name` 입력:
  - `corpCode.xml`에서 exact company_name 매칭 1건이면 `corp_code`로 해석 후 `list.json` 조회
  - 매칭 0건이면 `unresolved_company_name` 오류 반환
  - 매칭 2건 이상이면 `ambiguous_company_name` 오류 반환
- 추정/유사도 기반 매칭은 수행하지 않음

## 테스트 실행
```bash
python manage.py test apps.dart_analysis
```

## 참고
- 현재 단계에서는 **전체 공시 본문 파싱/신호 추출/평가/최종 한국어 리포트 생성**을 아직 구현하지 않았습니다.
- 다음 단계는 공시 카테고리 정규화와 핵심 시그널 추출 연결입니다.


## analysis 블록(1차 규칙 평가)
- `implemented`, `basis`, `risk_flags`, `positive_flags`, `neutral_flags`, `notes`, `evaluation_summary`를 반환합니다.
- 근거는 공시 목록 메타데이터 및 제목 기반 규칙(`report_nm`)으로 제한됩니다.
- 본문 파싱 전 단계이므로 최종 투자 판단으로 사용하면 안 됩니다.


## 원문 접근 메타데이터
- `/api/v1/dart/document`는 `rcept_no` 기준으로 `document.xml` 접근을 시도합니다.
- 현재 단계에서는 원문 본문 파싱 없이 `document_access`, `zip_inspection`, `xml_inspection`을 반환합니다.
- `xml_inspection`은 XML 구조 메타데이터(root tag, namespace, 최상위 child 태그/개수)만 제공합니다.
- strict XML 파싱 실패 시에는 `xml_parse_diagnostics`(line/column, XML 선언/인코딩 선언, 제한된 excerpt 등)를 반환합니다.
- strict 실패 후에는 `xml_fallback_inspection`을 시도하며, 현재는 XML 1.0 비허용 제어문자(U+0000~U+001F 중 TAB/LF/CR 제외)만 최소 치환 후 재파싱합니다.
- fallback 성공 시에도 `xml_inspection`은 strict 결과를 보존하기 위해 root/child를 채우지 않고, fallback 결과는 `xml_fallback_inspection`에 분리해 제공합니다.
- strict/XML fallback이 모두 실패하면 `markup_fallback_inspection`을 추가 시도하여, 태그 스트림 기반의 구조 정보(앞부분 태그 목록/얕은 수준 태그 순서/markup 형태 여부)만 보수적으로 제공합니다.
- markup fallback까지 실패하면 기존과 동일하게 `original_document_xml_inspection_failed` 오류를 반환하되 `xml_fallback_inspection`, `markup_fallback_inspection` 메타데이터를 함께 제공합니다.
- `document_outline`는 `markup_fallback_inspection`의 태그 구조 정보만으로 생성한 구조 요약 블록입니다(`has_body`, `has_cover`, `section_tag_names`, `tag_counts` 등).
- `document_outline`는 구조 정보만 다루며, 본문 의미 해석/비즈니스 라벨/투자 판단은 포함하지 않습니다.
- 본문 텍스트 추출/섹션 의미 해석은 아직 구현하지 않았습니다.


## 로컬 실데이터 ZIP 검증 스크립트 (Windows + VS Code)
현재 클라우드 환경에서 DART 외부 접근이 막힐 수 있으므로, 로컬에서 아래 명령으로 실데이터 검증을 수행할 수 있습니다.

### PowerShell (VS Code Terminal)
```powershell
$env:DART_API_KEY="YOUR_KEY"
python .\scripts\verify_dart_original_zip.py --corp-code 00126380 --page-count 5 --window-days 365
```

### 출력 필드
- `selected_corp_code`
- `selected_rcept_no`
- `download_succeeded`
- `valid_zip`
- `zip_entry_count`
- `zip_entry_names`

성공 시 실제 ZIP 엔트리 목록이 `zip_entry_names`에 출력됩니다.
네트워크 차단 시 오류 JSON(`error`, `detail`)을 그대로 출력합니다.
