# 러너스팟

전국 마라톤 대회를 찾아보는 러너스팟 사이트예요.

## 어떻게 돌아가나요

- `index.html` 사이트 화면 (별도 빌드 없이 Vercel이 그대로 띄워요)
- `data/races.json` 대회 데이터
- `posters/` 대회 포스터 이미지
- `scripts/collect.py` 대회 수집기
- `.github/workflows/collect.yml` 매일 아침 수집기를 자동 실행하고, 바뀐 내용을 저장해요. 저장되면 Vercel이 사이트를 자동으로 다시 배포해요.

## 설정

| 무엇 | 어디에 | 없으면 |
|---|---|---|
| 인스타그램 주소 | `config.js` 의 `IG_URL` | 인스타그램 첫 화면으로 연결 |
| 카카오 지도 JavaScript 키 | `config.js` 의 `KAKAO_JS_KEY` | 지도 대신 지도 앱 바로가기 |
| 카카오 REST API 키 | GitHub → Settings → Secrets and variables → Actions → `KAKAO_REST_KEY` | 장소 좌표를 못 구해서 지도가 안 떠요 |
| Anthropic API 키 | 같은 곳 → `ANTHROPIC_API_KEY` | 참가비·접수기간·시간표·포스터를 못 채워요 |

## 수동으로 바로 업데이트하고 싶을 때

GitHub 저장소 → Actions → 대회 정보 자동 수집 → Run workflow
