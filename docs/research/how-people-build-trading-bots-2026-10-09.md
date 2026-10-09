# 사람들은 자동매매 봇을 실제로 어떻게 만드나 — 강의·책·구축기 리서치 (2026-10-09)

> 앞선 리서치(`how-others-build-auto-trading-2026-10-04.md`)는 "어떤 전략이 돈이 되나"를 다뤘다.
> 이 문서는 **"어떤 순서와 기술로 만들고, 실제 운영하다 어디서 터지나"**를 다룬다.
> 범례: **[근거]** 공식 문서·PR·SEC 기반 분석 / **[일화]** 개인 블로그·포럼. 강의 내부는 공개 목차·소개 기준.

## 0. 한 줄 결론

강의는 "주문이 나가는 데까지"를 가르치고 끝난다. 실제로 돈을 날리게 만드는 건 전략이 아니라
**상태·시간·재시도** — 중복 주문, 재시작 후 기억 상실, 타임존, 오래된 데이터, "주문함"과 "체결됨"의 혼동이다.
오래 살아남은 1인 운영자(Rob Carver)는 이걸 **프로세스 분리, 주문 단계화, 매일 대사, 락, 백업**으로 막는다.

## 1. 강의가 가르치는 순서 (한국·해외 공통)

```
API 키 발급 → 시세 조회 → 잔고·주문 → 전략 하나 → 간단 백테스트 → 서버에 띄우기 → 메신저 알림
```

| 출처 | 유형 | 스택 | 특징 |
|---|---|---|---|
| 위키독스 『비트코인 자동매매』 | 무료 책 | pyupbit·ccxt·pandas | 지표·물타기·거미줄 매매·24시간 서버. 백테스트·리스크 장 없음 |
| 위키독스 『한국/미국 주식 자동매매』 | 무료 책 | 한투 KIS API, tmux, crontab, 텔레그램 | 주문 정정·취소까지 다룸. 백테스트 장 없음 |
| 조코딩 『AI 비트코인 자동매매』 (한빛) | 책·강의 | Upbit + GPT/Claude, EC2, Streamlit | "AI가 판단" MVP → 뉴스·차트 → DB·AI 회고 → 배포. 백테스트 얕음 |
| 인프런 코인봇 Part 1 (165,000원) | 강의 | REST+WebSocket, AWS EC2 | 김프 → 변동성 돌파 → 알림 → AWS |
| QuantInsti EPAT (6개월) | 강의 | Python, IBKR API, AWS | 통계·백테스트 중심. 공개 커리큘럼에 운영(ops) 모듈 없음 |
| Jansen 『ML for Algorithmic Trading』 | 책 | Zipline/Backtrader, ML | 23장 중 대부분 데이터·ML. 실운영 거의 없음 |
| Ernest Chan 『Algorithmic Trading』 | 책 | — | 1장에서 자동 실행을 독립 주제로 다루는 드문 책 |
| Alpaca 공식 튜토리얼 | 문서 | alpaca-py, `.env`, `paper=True` | try 하나가 에러 처리 전부. 스스로 "한 번 돌고 끝나는 봇은 프로덕션 아님"이라 적음 |
| Part Time Larry (YouTube) | 영상 | SQLite, Alpaca, cron | 포럼 평: 낡았고 타임존·중복 주문은 직접 해결 [일화] |
| QuantConnect LEAN | 플랫폼 | 클라우드 라이브 노드 | 재시작 시 현금·보유·미체결만 복구, 나머지 상태는 사용자 몫이라고 명시 [근거] |

**실행 방식 실태(한국)**: `while True` + `sleep`으로 "9시인지" 확인하는 방식이 대부분, 주식은 crontab.
배포는 AWS → 비용 때문에 오라클 무료 서버("Out of host capacity" 흔함), 라즈베리파이, 집 PC.
`nohup` / `tmux`로 띄우고 로그는 수동 정리. 검증은 사실상 **"소액으로 돌려보기" 하나**. 주식은 증권사 모의투자가 있어 조금 낫다.

## 2. 강의가 건너뛰는 것 = 실제로 사고 나는 곳

| 문제 | 실제 사례 | 근거 |
|---|---|---|
| **중복 주문** | 응답을 못 받고 재시도 → 거래소는 이미 처리함. "응답 없음 ≠ 처리 안 됨". 모든 주문에 고유 ID 필요 | [일화] dev.to |
| **재시작 후 기억 상실** | 봇이 "오늘 이미 샀는지" 잊고 또 삼. 겪은 사람들이 state.json·SQLite를 뒤늦게 추가 | [일화] 다수 |
| **"주문함" ≠ "체결됨"** | 4일간 `placed=1`, `placed_ok=0`. 실행과 검증을 같은 코드가 해서 같은 착각을 공유 → **"봇이 자기 감사자가 되면 안 된다"** | [일화] dev.to |
| **타임존** | 서버 UTC, 시장 ET → 장 마감 루틴이 데이터 확정 전에 실행. 고정 시각 테스트는 전부 통과. 라즈베리파이 봇은 일일 손익이 자정에 안 리셋돼 매매 정지 | [일화] |
| **브로커 재연결** | IB Gateway 야간 재시작 때 프로세스 사망, timeout 655건 → 3층 재시도로 해결하되 **주문 함수만은 재시도에서 제외** | [일화, 상세] |
| **비용 착각** | 비용 반영하자 MA 교차 수익 중앙값 28% → 2.8%. 문서상 수수료와 실제가 6~12배 차이 사례 | [일화] |
| **페이퍼 ≠ 실전** | 섀도 백테스트 +0.355%/거래 vs 실전 −1.10%/거래. 심리와 포지션 크기 | [일화] HN |
| **프레임워크 버그** | pysystemtrade 1.8.3을 페이퍼로 돌리다 버그 8건 발견(부분 체결이 완료로 처리되는 등) → 페이퍼는 **버그 찾는 단계**이기도 함 | [근거] PR |
| **배포 사고** | Knight Capital 2012: 서버 8대 중 1대 배포 누락 + 재사용 플래그가 죽은 코드를 깨움 → 45분 $440M. 경고 메일 97통은 아무도 안 봄 | [근거] SEC 기반 |
| **API 제약** | KIS 토큰 발급 횟수 제한(캐시 필수), 키움 OpenAPI+ 3.6초 간격, 웹소켓이 조용히 끊김 | [근거] 공식 문서 |

## 3. 오래 살아남은 1인 운영: Rob Carver의 pysystemtrade [근거: docs/production.md, 블로그]

- **구성**: Linux + IB Gateway + MongoDB(상태) + Parquet(시세) + crontab. 프로세스마다 따로 돌고 끝나며, DB로만 소통.
- **하루 흐름**: 장중엔 주문 실행기만 계속 돈다. 장 마감 후 순서대로 — 환율·계약 갱신 → 가격 갱신(이상치 감지) → 자본 갱신 → 시스템 재계산(목표 포지션) → 주문 생성 → 리포트 → 백업 → 정리.
- **주문 3단계**: 전략 주문 → 계약 주문 → 브로커 주문. 체결은 아래에서 위로 올라온다. 전략 코드와 실행 코드가 이 층으로 분리.
- **락**: 기록 포지션 ≠ 브로커 포지션이면 **자동으로 거래 잠금**, 일치하면 해제. 실행 중 중복 주문 방지 락, 수동 종목 락.
- **리포트**: 대사·상태·슬리피지·비용·리스크·유동성·손익. 메일 알림은 **CRITICAL일 때만**(알림 피로 방지).
- **하드웨어**: 같은 PC 2대(대기 1대) + 감시용 소형 PC, NAS 야간 백업 + USB + 오프사이트. 페일오버는 수동 절차. 정전·인터넷 장애는 본인도 "미해결"이라 인정. **느린 추세추종이라 가능한 설계**라고 명시.

## 4. 튜토리얼 봇 vs 프로덕션 봇

| 항목 | 튜토리얼 봇 | 프로덕션 봇 |
|---|---|---|
| 실행 | `while True` 하나 / cron 스크립트 하나 | 목적별 프로세스 분리(데이터·신호·주문 생성·실행·리포트·백업) |
| 진실의 원천 | 봇 내부 변수 | 거래소. 내부 상태는 "현재의 이해"일 뿐이고 주기적으로 대사 |
| 주문 | `submit_order()` 호출로 끝 | 상태 머신(생성→제출→접수→부분→체결/불명), 고유 ID, **주문은 재시도 안 함** |
| 재시작 | 기억 상실 | 상태 로드 → 미체결 조회 → 대사 → 리스크 확인 → 재개 |
| 데이터 | 받은 대로 사용 | 신선도 검사(오래되면 중단), 이상치 감지, 확정 봉만 |
| 시간 | `datetime.now()` | 시장 타임존·휴장·거래시간·브로커 정기 재시작 반영 |
| 비용 | 고정 % 가정 | 실측 수수료 확인, 결정가 대비 체결가 리포트 |
| 검증 | 백테스트 → 페이퍼 → 실전 | + 소액 실전으로 가정 검증, 페이퍼는 버그 찾기 단계 |
| 감시 | print / 로그 파일 | 계층별 헬스체크, 행동 필요한 것만 알림, 구조화 로그 |
| 비상 | 프로세스 kill | 킬스위치, 포지션 락, 청산만 허용 |
| 인프라 | 노트북, 무료 클라우드 | Docker 또는 대기 머신, 백업, **복구 리허설** |
| 검증 독립성 | 같은 코드가 실행하고 성공도 판정 | 거래소 응답·리포트를 실행 코드와 **다른 경로**로 확인 |

## 5. 우리 저장소 대조와 v3 실행기 체크리스트

**이미 프로덕션 쪽에 있는 것**: RiskGate(사전 검증), 파일 영속 킬스위치(청산만 허용), 거래소 대사 + 불일치 시 정지(= Carver의 position lock),
체결 품질 기록(결정가 vs 체결가), 확정 봉만 쓰는 백테스트, 데모 강제, Docker, 텔레그램 알림 모듈.
대부분의 한국 강의·구축기보다 앞서 있다.

**v3(BTC + 추세 필터) 실행기를 만들 때 반드시 넣을 것** — 위 사고 사례에서 나온 목록:

1. **고유 주문 ID(`clOrdId`) + 주문은 자동 재시도 금지.** 응답이 없으면 같은 ID로 *조회*해서 확인한다.
2. **상태를 디스크에 저장하고, 시작할 때 거래소와 먼저 맞춘 뒤** 매매를 재개한다(재시작 = 동기화 → 확인 → 재개).
3. **"주문 시도"와 "체결 확인"을 따로 기록**하고, 체결 확인은 실행 코드와 다른 경로(대사 루프, 일일 리포트)에서 한다.
4. **데이터 신선도 검사**: 최신 일봉이 기대 시각보다 오래됐으면 판단하지 않는다.
5. **시간은 UTC 하나로**: 일봉 경계(`1Dutc`), 자정 리셋, OKX 정기 점검 시간을 명시적으로 처리.
6. **멱등한 하루 1회 실행**: 같은 날 두 번 돌아도 두 번 사지 않는다(처리한 봉 기록, 단 주문 성공 *후*에만 기록 — v1 데모 트레이더에서 실제로 겪은 버그).
7. **알림은 행동이 필요한 것만**: 매매 발생, 대사 불일치, 킬스위치 발동, 데이터 지연. 정상 동작은 일일 요약 1통.
8. **`bot/state/` 백업과 복구 리허설**: 컨테이너를 지우고 다시 올려도 같은 상태로 돌아오는지 한 번은 직접 확인.

v3는 하루 1번 확인하고 1년에 몇 번만 매매하는 **느린 전략이라 이 체크리스트를 다 지키기 쉬운 형태**다. Carver가 말한 "느린 추세추종이라 가능한 설계"와 같은 위치다.

## Sources

**한국**: wikidocs.net/21811 · /151577 · /120390 · /book/7845 · m.hanbit.co.kr/store/books/book_view.html?p_code=B5063161940 · jocoding.net/courses/gpt-bitcoin-futures · udemy.com/course/gpt-bitcoin-ai-agent · inflearn.com/course/비트코인-암호화폐-자동매매-1 · velog.io/@johoon815/비트코인-자동매매-Ch.4-여기서-완성 · tgparkk.github.io/stock/2025/03/08/auto-stock-1-init.html · algolab.co.kr/blog/kiwoom-rest-api-algotrading-guide-2026 · velog.io/@1rock/AICOINTRADINGBOT · velog.io/@abby0616/파이썬으로-만드는-주식-자동매매기-후기 · github.com/rlagustn92/upbit-signal-bot · github.com/kimyongin/fin/issues/49 · github.com/EST-team-project/Qurious/issues/66 · leeminjoo.github.io/파이썬으로-업비트-자동매매/2021/06/27/Backtesting.html · clien.net/service/board/cm_vcoin/18084474 · apiportal.koreainvestment.com/provider-doc4

**해외**: quantinsti.com/epat · oreilly.com/library/view/machine-learning-for/9781839217715 · oreilly.com/library/view/algorithmic-trading-winning/9781118746912 · alpaca.markets/learn/how-to-build-stock-trading-bot-with-alpaca · forum.alpaca.markets/t/has-anyone-here-finished-part-time-larrys-stock-trading-app-tutorial/6591 · quantconnect.com/docs/v2/cloud-platform/live-trading/deployment · freqtrade.io/en/stable · raw.githubusercontent.com/robcarver17/pysystemtrade/master/docs/production.md · qoppac.blogspot.com/2013/12/p-margin-bottom-0.html · qoppac.blogspot.com/2021/12/my-trading-system.html · github.com/pst-group/pysystemtrade/pull/1671 · plaintape.substack.com/p/daily-price-update-crashes-at-midnight · dev.to/pavloaser23/i-thought-the-hardest-part-of-a-trading-bot-was-the-strategy-i2c · dev.to/casatrick/what-it-actually-takes-to-run-a-polymarket-trading-bot-247-3209 · dev.to/botandbull/the-bug-that-passed-every-test-and-still-lost-me-money-1gl5 · dev.to/jugeni/60-of-my-921-wasnt-strategy-the-other-40-wasnt-even-visible-4m30 · news.ycombinator.com/item?id=16923294 · dougseven.com/2014/04/17/knightmare-a-devops-cautionary-tale

접근 제한: 일부 Medium·위키독스 본문은 403으로 목차·검색 요약만 사용. 유료 강의 내부 자료는 미확인.
