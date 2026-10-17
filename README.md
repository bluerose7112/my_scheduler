# My Scheduler

과제(project) → 아이템(item) → 서브아이템(subitem) 계층의 JIRA 스타일 스케줄러.
pywebview + SQLite. 입력은 **로컬 LLM**(OpenAI 호환 `/chat/completions`)로 대신합니다.

## 실행
```
pip install -r requirements.txt
python run.py                     # 데스크톱 창 (pywebview)
python -m scheduler.devserver     # 브라우저 개발용 (http://127.0.0.1:8765)
```
DB는 실행 파일(.exe) 옆 `scheduler.db`에 생성됩니다 (개발 시 저장소 루트).

## 화면
- 간트 / 리스트 / 텍스트 탭. 항목 클릭 시 우측에서 모든 속성(상태, 우선순위, 담당자, 보고자, 라벨, 시작/마감일, 예상시간, 진행률, 설명) 편집.
- 항목(간트 막대/이름, 리스트 행)을 클릭하면 세부정보 팝오버가 열려 모든 속성을 편집합니다. 설명/제목에 `[[P1-2]]`처럼 쓰면 항목 간 링크(그래프)가 되고, 팝오버에 연결/백링크가 표시됩니다.
- 오른쪽 어시스턴트 패널(Cursor 스타일, 경계선 드래그로 폭 조절): 일정 입력·수정·질문을 한 창에서 처리합니다. 변경은 **즉시 반영**되고 “되돌리기”로 마지막 변경을 취소합니다.
  - LLM에는 항목 전체를 통째로 주지 않고 압축된 목록(키/제목/상태/마감)만 줍니다. 상세는 LLM이 `search`(키워드·상태·담당자·기간 필터)와 `get`(필드+부모/자식+링크/백링크) 도구를 직접 호출해 필요한 만큼 가져옵니다. 데이터가 커져도 컨텍스트가 폭발하지 않습니다.
  - 도구 호출은 JSON 텍스트 프로토콜이라 네이티브 function-calling이 없는 로컬 모델에서도 동작합니다.
- “LLM 설정”: 서버 주소(예: LM Studio `http://localhost:1234/v1`, Ollama `http://localhost:11434/v1`), 프로토콜, 모델, 타임아웃.

## 빌드 (.exe)
```
pip install -r requirements-dev.txt
python build.py        # dist/scheduler.exe
```
버전 표기는 `git describe` 기반: `v1.2.0`(태그 일치), `v1.2.0(+3)`(태그 후 3커밋), 끝의 `+`는 dirty(미커밋 변경).

## CI / 릴리스
- `.github/workflows/ci.yml`: 푸시/PR마다 pytest(Linux) + Windows `.exe` 빌드 검증(artifact 7일 보관).
- `.github/workflows/release.yml`: `v*` 태그를 푸시하면 Windows에서 테스트 → 빌드 → 임베드된 버전이 태그와 일치하는지 확인 → GitHub Release에 `scheduler.exe` 첨부.
```
git tag v0.1.0 && git push origin v0.1.0
```

## 테스트
`python -m pytest`
