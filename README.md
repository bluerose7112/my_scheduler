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
- 하단 입력창: 자연어를 입력하면 LLM이 생성/수정 작업을 만들어 **즉시 반영**합니다. “되돌리기”로 마지막 LLM 입력을 취소.
- “LLM 설정”: 서버 주소(예: LM Studio `http://localhost:1234/v1`, Ollama `http://localhost:11434/v1`), 프로토콜, 모델, 타임아웃.

## 빌드 (.exe)
```
pip install -r requirements-dev.txt
python build.py        # dist/scheduler.exe
```
버전 표기는 `git describe` 기반: `v1.2.0`(태그 일치), `v1.2.0(+3)`(태그 후 3커밋), 끝의 `+`는 dirty(미커밋 변경).

## 테스트
`python -m pytest`
