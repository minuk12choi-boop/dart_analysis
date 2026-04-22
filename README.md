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

### 예시 3: corp_code 기반 최종 소비자용 보고 JSON 조회
```bash
curl "http://127.0.0.1:8000/api/v1/dart/report?corp_code=00126380"
```

### 예시 4: rcept_no 기반 원문 접근 메타데이터 조회
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
- `analysis.document_structure_signals`는 `document_structure_enrichment`를 재집계한 구조 신호 요약입니다(heading 후보 가용 건수, section/table/cover/body/summary 유사 구조 건수 등).
- `analysis.document_structure_signals`는 구조 수준 집계만 제공하며, heading 텍스트 의미 해석/비즈니스 결론은 포함하지 않습니다.
- `analysis.document_structure_hints`는 `document_structure_signals`를 기반으로 만든 정보성 플래그 집합입니다(`structured_document_detected` 등).
- `analysis.document_structure_hints`는 구조 존재 여부를 표시할 뿐, 의미 해석/사업 결론/투자 판단을 제공하지 않습니다.

## report 엔드포인트(최종 소비자용 JSON)
- `/api/v1/dart/report`는 내부적으로 validate 구조 데이터를 재사용해 소비자용 블록으로 재구성합니다.
- 주요 블록:
  - `request`
  - `report_meta`
  - `executive_summary`
  - `key_findings`
  - `caution_findings`
  - `structure_findings`
  - `disclosure_cards`(기본 최대 3건)
  - `limitations`
  - `status`
- `disclosure_cards`는 검증된 기존 필드만 사용합니다(rcept_no/report_nm/rcept_dt, 정규화 카테고리, 감지 신호, 타입별 규칙/사실/힌트, 구조 미리보기 등).
- `disclosure_cards`의 preview 필드는 소비자 가독성을 위해 품질 필터를 적용합니다.
  - 공백 정규화/길이 제한
  - 마크업 잔재(`<...>`, `VALIGN="..."` 등)로 판단되는 문자열 억제
  - 노이즈가 심한 값은 빈 목록으로 반환(대체 문구 생성 없음)
- 본문 재파싱/새 의미 추론/투자 추천은 수행하지 않습니다.

## report_preview 블록(사람 친화 미리보기)
- `/api/v1/dart/validate`는 기존 기계 친화 블록과 별도로 `report_preview`를 제공합니다.
- `report_preview`는 이미 검증된 데이터(`normalized_items`, `summary`, `analysis`, `document_structure_enrichment`)만 재구성합니다.
- `report_preview` 주요 필드:
  - `summary_line`: 보수적 1줄 요약
  - `key_points`: 핵심 포인트 목록
  - `caution_points`: 해석 유의사항 목록
  - `structure_notes`: 구조 신호/힌트 요약 목록
  - `disclosure_preview_cards`: 공시 카드 미리보기(최대 3건)
  - `limitations`: 해석 경계(제목/구조 기반, 본문 의미 해석/투자 판단 미포함)
- `report_preview`는 문서 enrichment가 일부 실패해도 가능한 범위에서 생성되며, validate 전체 응답 실패를 유발하지 않습니다.

## type-specific 블록(1차 타입별 규칙 팩)
- `/api/v1/dart/validate`는 `type_specific_analysis`, `type_specific_summary`를 함께 반환합니다.
- 이 블록은 다음 안전 입력만 사용합니다:
  - `report_nm`
  - 정규화 카테고리
  - 제목 기반 신호(`detected_signals`)
  - `document_structure_enrichment`의 제한적 구조 정보
- 초기 지원 타입(1차 규칙):
  - `rights_offering_or_capital_increase`
  - `convertible_bond_or_bond_with_warrant`
  - `ownership_or_major_shareholder_change`
  - `supply_or_business_contract`
  - `periodic_report`
- 각 공시 항목은 `matched_type_rule`, `type_specific_facts`, `type_specific_hints`, `limitations`를 제공합니다.
- 지원 대상이 아닌 공시는 `status: not_applicable`로 반환되며 validate 전체 응답은 유지됩니다.
- 이 단계는 타입별 사실/주의 힌트만 다루며, 본문 의미 해석/투자 판단/최종 내러티브 리포트는 포함하지 않습니다.

## validate 응답의 문서 구조 enrichment(선택적)
- `/api/v1/dart/validate`의 `disclosures.data.document_structure_enrichment`는 공시 목록 중 제한된 건수(현재 기본 1건)에 대해 문서 구조 신호를 추가로 제공합니다.
- 제공 정보는 `document_outline`/`document_heading_candidates`에서 파생한 구조 신호만 포함하며, 의미 해석/비즈니스 라벨은 포함하지 않습니다.
- 문서 fetch/검사 실패 시에도 validate 전체 응답은 유지되며, 개별 항목에 `status`, `error`로 실패 상태를 반환합니다.
- `document_structure_enrichment.items[*].text_extract_preview`는 같은 제한 건수 범위에서 추출한 안전한 텍스트 미리보기를 제공합니다.
- `text_extract_preview`는 짧은 텍스트 조각/토큰만 포함하며, 본문 의미 해석이나 투자 판단은 제공하지 않습니다.

## 운영 안정화(업스트림 접근)
- `DartClient`는 인-프로세스 로컬 캐시를 사용합니다(기본 활성화).
  - corpCode 조회: 기본 TTL 24시간
  - 공시 목록 조회: 기본 TTL 10분(종목/조회창/날짜 기준 키)
  - 원문 문서 조회: 기본 TTL 10분(`rcept_no` 기준 키)
- 업스트림 요청은 보수적 타임아웃/재시도 설정을 사용합니다.
  - 기본 타임아웃: 20초
  - 기본 재시도: 1회(일부 재시도 가능 오류 코드/네트워크 오류)
- `/api/v1/dart/validate`, `/api/v1/dart/document`는 `upstream_status`, `cache_status`를 포함해
  최근 업스트림 시도 상태/캐시 히트·미스·쓰기 상태를 기계적으로 확인할 수 있습니다.
- 업스트림 실패 시에도 가능한 범위에서 구조화된 상태 블록을 유지해 진단 가능성을 높였습니다.


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
- `document_heading_candidates`는 markup 기반으로 수집된 heading-like 태그(`title`, `cover-title`, `document-name` 등)에서 raw 텍스트 후보만 보수적으로 추출한 블록입니다.
- `document_heading_candidates`는 공백 정규화/빈 문자열 제거만 수행하며, 요약/의미 해석/비즈니스 라벨링은 수행하지 않습니다.
- `document_text_extract`는 heading 후보와 markup fallback excerpt를 기반으로 한 안전한 최소 텍스트 추출 블록입니다.
- `document_text_extract` 범위:
  - 짧은 heading 텍스트 후보
  - 짧은 plain-text snippet
  - table 태그 존재 시 tag 기반 label 후보
  - snippet에서 직접 매칭된 숫자/날짜/비율 토큰 후보
- `document_text_extract`는 `extraction_attempted`, `extraction_succeeded`, `extracted_from`, `limitations`를 제공하며, 추출이 안전하지 않으면 비성공 구조로 반환됩니다.
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
