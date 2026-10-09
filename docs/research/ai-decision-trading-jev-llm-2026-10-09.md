# AI에게 매매 판단을 맡기는 시스템 — TypeSafe Jev와 LLM 트레이딩 리서치 (2026-10-09)

> 질문: TypeSafe AI의 Jev(2026-09-15 공개)나 LLM에게 매매 판단을 맡기는 자료·오픈소스·블로그는 어떻게 만들고, 실제로 통하는가.
> Part A = Jev와 Jev 트레이딩 프로젝트, Part B = LLM이 매매를 결정하는 프로젝트와 그 증거. Part 0은 둘의 종합.
> Jev는 이 문서 작성 모델의 학습 이후 출시되어, 조사 결과에 있는 내용만 적었다.

## Part 0. 종합

### 1. 결론: AI에게 "사라/팔아라"를 맡겨서 비용 차감 후 꾸준히 버는 증거는 없다

| 증거 | 결과 |
|---|---|
| Alpha Arena S1 (실제 $10k × 6 LLM, 크립토 선물) | 4개 손실, GPT-5 −60% 이상. 우승 Qwen +22% |
| Alpha Arena S1.5 (미국 주식, 32계좌) | 6계좌만 플러스, 합계 **−35.2%**. **S1 우승자 Qwen은 4개 모드 모두 손실** |
| StockBench (오염 통제) | 대부분 동일가중 매수-보유(+0.4%)를 못 넘음, 최고 +2% |
| LiveTradeBench (21개 LLM, 50일 실시간) | 일반 지능 점수와 매매 성과 상관 ≈ 0 (주식 0.05, Polymarket −0.38) |
| FINSABER (20년, 100+ 종목 재검증) | FinMem·FinAgent 우위 사라짐. 강세장 Sharpe 매수보유 0.61 vs FinAgent 0.12, FinMem −0.19 |
| Profit Mirage (7개 프레임워크) | 모델 학습 cutoff 이후 Sharpe **51–62% 하락** → 이전 구간 백테스트는 "기억"일 수 있음 |
| Jev 방향 예측 (jev_stock, 공개된 유일한 정량 결과) | 120건 중 45%, 3지선다라 무작위와 큰 차이 없음. 저자가 look-ahead 가능성 인정 |
| 조코딩 o1 / OKKY o3-mini | +35%(본인 "들고 있는 게 더 이득") / −11.6%(시장 −9.8%보다 못함) |

### 2. Jev는 "LLM의 빠르고 싼 버전"이 아니라 "판단 전용 부품"이다

글을 쓰지 않고, 상태(JSON)와 질문을 넣으면 **확률이 붙은 답**(예/아니오, 선택지, 점수)을 0.1~0.5초에 준다. 입력 100만 토큰에 $0.042.
일반 분류 과제에서는 독립 평가로 **보정이 잘 된다**(Choice ECE 0.028)는 게 확인됐지만, **금융·가격 예측으로 평가된 적은 없다.**
벤더 스스로 수학·숫자·날짜 비교를 못 한다고 밝힌다. 데이터 cutoff 미공개라 과거 백테스트는 오염 가능하고, 검증은 **앞으로 기록하는 방식(shadow/paper)**만 믿을 수 있다.

### 3. 진지한 프로젝트는 전부 같은 구조로 모인다: "AI는 판단, 코드는 집행"

1. 코드가 데이터를 모으고 지표를 계산한다.
2. 숫자를 **라벨로** 바꾼다("추세: 강한 상승", "변동성: 높음") — Jev·LLM은 숫자보다 라벨에 강하다.
3. AI가 **좁은 질문 하나**에 답한다("지금 레짐은?", "이 신호가 근거와 일관적인가?").
4. 코드가 임계값으로 행동을 정한다.
5. 코드의 **하드 리스크 규칙이 거부권**을 가진다.
6. 코드가 주문·기록·대사를 한다.

공통 금기: **청산·손절·포지션 한도는 절대 AI에게 맡기지 않는다.** nofx(Go 런타임이 LLM 주문을 하드 리밋으로 자름), QuantDinger(Jev를 주문 직전 관문으로), buberlo/jev-trader(판단 6개를 따로 묻고 정책 엔진이 조합, Brier/ECE로 보정 기록), nodefiend(Jev를 예측이 아닌 **감사자**로 shadow 모드)가 이 형태다.
반대로 TradingAgents처럼 리스크 관리까지 LLM 에이전트가 하는 구조는 하드 리밋이 아니고, 저자 스스로 재현성을 부인한다.

### 4. 이 저장소에 쓴다면

이미 갖춘 RiskGate·킬스위치·대사·TCA·사전 등록이 바로 "코드가 집행" 쪽이다. AI를 붙인다면 자리는 하나다:

- **v3(BTC + 100일선 필터)의 보조 판단으로 shadow 기록만.** 예: 매주 Jev에 "현재 레짐: 상승 추세 / 횡보 / 하락 추세 / 급변" Choice와 "필터 신호를 뒤집을 만한 근거가 있는가" Noul을 묻고, **매매에는 쓰지 않고** (질문, 답, 확률, 이후 결과)만 쌓는다.
- 몇 달 뒤 Brier score와 "AI 판단을 따랐다면" 반사실 성과를 사전 등록 기준으로 평가해서, 기준을 넘으면 그때 진입 필터로 승격한다.
- 비용은 무시할 수준(주 1회 호출이면 월 1센트 미만)이고, 위험은 0(매매에 안 쓰므로)이다.
- AI에게 방향을 직접 맡기는 형태(jev-trader, Alpha Arena식)는 증거상 하지 않는다.

---
## Part A. TypeSafe AI Jev와 Jev 트레이딩 프로젝트

### A-1. Jev의 기술적 정체

**확인된 사실(Cloudflare 모델 카드, OpenRouter, InfoQ).** TypeSafe AI(전 OpenAI 연구원 Diogo Almeida 창업)가 2026-09-15 공개한 첫 "System One Model". 텍스트를 생성하지 않는다. `state`(string 또는 JSON) + typed `questions`를 single parallel pass로 평가한다. question type은 세 가지:

- **Noul**: yes/no 명제가 참일 확률(0-1). `{"type":"noul","noul":0.83}`. 별도 confidence 없음.
- **Choice**: 고정 option 중 하나 + `confidence` + option별 `probabilities`.
- **Score**: 순서 있는 level(최대 10)의 확률 가중 평균 `score`, `confidence`, `legend`, `probabilities`.

질문 구조 `{type, instructions, criteria}`, 응답에 `model`(예: `jev-1.13.0`)·`answers`·`usage`. context 32k(요청당 64k), 입력은 text만(이미지·오디오 불가). 입력 $0.042/1M tokens, 출력 무료. Cloudflare 카드 기준 data retention zero. proprietary(weights·논문 없음), 학습은 "RLCD(Reinforcement Learning for Calibrated Decisions)"라고만 공개. **데이터 cutoff 미공개.**

**벤더 주장**: latency 70-500ms, LLM 대비 "193.6x faster, 444.6x cheaper", "zero hallucinations"(= 출력이 schema로 제한된다는 뜻일 뿐. "type은 맞는데 값이 틀린 답"은 가능하다고 InfoQ·문서가 인정).
벤더 jaggedness 페이지(jev-1.13)의 failure mode 9개: literal reading, math/numbers, date/time 비교, indirection, 관련 없는 정보가 많은 큰 state, adversarial content, 모순 criteria, Choice option 순서 의존, generation. 권고: 수학은 코드로, 버전 pin.

**독립 평가** (Bonn대·Lamarr Institute, arXiv 2609.37647, 37개 데이터셋, 346,009 requests):

| 항목 | 결과 |
|---|---|
| Choice calibration (pooled ECE) | 0.028, 잘 보정 |
| 단일 binary (Noul) ECE | 0.052, 약간 underconfident |
| multi-label binary ECE | 0.168, yes 과대 예측 |
| 평균 latency | 0.36s |
| Qwen3.8-27B 대비 | 37개 중 27개 우세 |
| 약점 | 저자원 언어, 세밀한 label(Emotion 58.5%), 법률(AGB-DE F1 0.204) |

**금융·가격 예측 과제는 평가에 없다.** 이 calibration을 시장 예측으로 옮길 근거 없음. 현장 사례(Vercel 5-18x 속도, Bryo AI "Gemini가 약간 더 정확하지만 10-20배 비쌈")도 분류 작업 한정.

### A-2. Jev 트레이딩 프로젝트

| 프로젝트 | Stack / Venue | Jev에게 묻는 것 | 코드 담당 / risk control | 결과(신뢰도) | License / Stars* |
|---|---|---|---|---|---|
| jarrodwatts/jev-trader | Bun/TS, Monad Kuru MON-USDC | 매 block(~300ms) buy/sell/hold, 100 block(~30s) 방향 | 호가, post-only limit 1 tick inside, position cap | dry-run, 성과 미공개 | MIT / 1.3k-2.9k |
| aowang-ai/jev-trade | Bun + Next.js, Hyperliquid perp | 매 tick long/short → open/close/hold | 5개 sleeve 지갑 분리, $40 notional, IOC exit 5bp | live P&L 표시, 검증된 기간 수익 없음 | MIT / ~199 |
| OpenByteInc/QuantDinger | Python/Flask/Postgres, crypto·주식·FX | entry 직전 pre-trade gate(Choice): evidence quality, signal consistency, regime, account risk, execution quality | 기본 risk 실패 시 Jev 생략·reject, timeout 시 **fail-open**, exit/SL/TP는 Jev 우회, paper 기본 | 성과 없음 | Apache-2.0 / ~12k |
| buberlo/jev-trader | Python, paper(+VenueAdapter) | 6개 atomic 판단: regime, direction, toxic_flow, liquidity_stressed, quote_environment, inventory_pressure | policy engine(threshold 조합), hard veto·kill switch는 위임 안 함, (state, decision, outcome) JSONL → Brier/ECE/Platt | Phase 0(paper)만 | MIT / ~42 |
| VGabriel45/polymarket-btc5m-jev-trading | Node 20, Polymarket BTC 5분 | ~5초마다 window 종료 시 시가 위인지 | confidence ≥0.90, window당 1회, FOK, $5, dry-run 기본 | 결과 없음 | — / ~43 |
| sushant-mishra-dtu/TradingAgents-Jev | Python LangGraph, 미국 주식 | 소셜 글 relevance·중복·prompt injection, debate early-stop, PM thesis vs 보고서 모순 검증 | 집계는 코드, 내러티브는 LLM, point-in-time 데이터 | 연구용, 결과 없음 | Apache-2.0 / 0 |
| nodefiend gemini_snap_flash (dev.to) | Python, MT5 prop, FX 1h | Noul: "방향 판단이 자기 thesis와 일관적인가" (예측 아닌 감사) | Gemini vision이 방향, 일일 손실 2% cap, 4연패 kill, 고정 SL/TP | **SHADOW_MODE 꺼져 있어 Jev 감사 0건.** 사전 등록 기준 통과 시 승격 | 블로그 |
| sosopop/jev_stock | Python, 홍콩 주식 4종 | Choice up/flat/down (T+1, ±0.3%) | 과거 30세션 지표만 state로 | **120건 중 54건 = 45.0%.** 저자가 look-ahead 가능성 인정 | — / ~16 |

*Stars는 시점·출처마다 크게 다름.

drillan 서베이 gist는 그 밖에 kraken 페이퍼 봇, Paperline(Kuru 페이퍼), Gamma-Software jev-signals-lab(12개 질문을 trend>.75 AND momentum>.70 같은 rule engine으로 조합)을 정리. 전부 paper/POC.

### A-3. 반복되는 아키텍처: "Jev judges, code executes"

Apex-Logic 권고 6단계: ① 코드가 데이터 수집·feature 계산 ② feature를 **labeled categorical state**로 변환(숫자 그대로보다 label이 잘 통함) ③ Jev가 좁은 typed question에 답 ④ 코드가 threshold로 action 변환 ⑤ 코드의 hard risk rule이 veto ⑥ 코드가 주문·로깅.
LangChain 하네스 글, Microsoft agent-framework #8556도 같은 구도: Jev는 빠른 control-plane 판단(routing, tool-call risk gate), 느린 open-ended reasoning은 LLM.

두 갈래: **(a) 초저지연 crypto**(Monad, Hyperliquid, Polymarket) — Jev를 방향 신호로 직접 사용 / **(b) gate·auditor형**(QuantDinger, buberlo, TradingAgents-Jev, nodefiend) — pre-trade filter, 일관성 감사, 뉴스 triage만.
공통 규칙: **exit, stop-loss, position limit은 절대 Jev에 맡기지 않는다.**

### A-4. 한계와 비판

- **수학·시간 불가**: returns, spread, indicator, sizing, 날짜 비교, counting은 벤더 스스로 금지. 차트 이미지도 못 넣음.
- **예측력 증거 없음**: 공개된 유일한 정량 방향성 결과가 jev_stock 45%(120건, 3-class라 무작위와 큰 차이 없음). Apex-Logic: "형식이 맞는 답이 수익을 뜻하지 않는다". 고빈도 crypto 봇 중 검증 가능한 기간 수익·비용 반영 백테스트를 낸 곳 없음.
- **Look-ahead**: 학습 cutoff 미공개 → 과거 재현 백테스트는 오염 가능. 신뢰 가능한 검증은 **prospective(paper/shadow)뿐**. nodefiend·buberlo가 사전 등록 기준과 calibration logging으로 대응.
- **Calibration drift**: question type별 편향 방향이 다름, 금융 도메인 calibration 측정 없음. 버전이 바뀌면 동작도 바뀜 → version pin + 자체 reliability curve 필요.
- **Vendor lock-in**: closed weights, 단일 벤더 API. QuantDinger는 장애 시 fail-open(= gate가 꺼짐).
- **Blow-up**: 공개된 Jev 기인 대형 손실은 없음.

### A-5. API 호출 예시

OpenRouter SDK:
```javascript
const decision = await openrouter.alpha.decisions.create({
  decisionsRequest: {
    model: 'typesafe/jev-1.13',
    state: 'I upgraded to Pro yesterday but got charged. Which one is it?',
    questions: {
      team: {
        type: 'choice',
        instructions: 'Which team should handle this?',
        criteria: {
          billing: 'Charges, invoices, and refunds',
          technical: 'Bugs, outages, broken features',
          account: 'Login, password, profile changes'
        }
      }
    }
  }
});
```
LangChain: `from langchain_typesafe import Noul, TypeSafeClassifier` → `classifier.invoke({"state": ..., "questions": {"urgent": Noul(instructions="Does this need attention right now?")}})` → `response.nouls["urgent"].noul`.
Native REST: `POST https://api.typesafe.ai/v1/systemone`.

### Sources (Part A)
typesafe.ai · docs.typesafe.ai · docs.typesafe.ai/model-jaggedness/jev-1.13 · developers.cloudflare.com/ai/models/typesafe/jev · openrouter.ai/blog/insights/what-is-jev · infoq.com/news/2026/10/typesafe-ai-jev-released · langchain.com/blog/building-a-harness-with-jev · apex-logic.net/news/jev-ai-model-for-trading-2026 · dev.to/nodefiend/jev-assisted-llm-trading-ofa · gist.github.com/drillan/6916b16e8ea31a8ec36c8f59d6483150 · github.com/walidboulanouar/awesome-jev-use-cases · github.com/jarrodwatts/jev-trader · github.com/aowang-ai/jev-trade · github.com/OpenByteInc/QuantDinger · github.com/buberlo/jev-trader · github.com/VGabriel45/polymarket-btc5m-jev-trading · github.com/sushant-mishra-dtu/TradingAgents-Jev · github.com/sosopop/jev_stock · kenhuangus.substack.com/p/jev-returns-typed-probabilities-at · github.com/microsoft/agent-framework/issues/8556 · arxiv.org/html/2609.37647v1
(403으로 미반영: marktechpost "20 agentic use cases", Medium pravvich 벤치마크)

---

## Part B. LLM이 매매를 결정하거나 승인하는 시스템

### B-1. 주요 오픈소스

- **TauricResearch/TradingAgents**: fundamentals·sentiment·news·technical analyst 병렬 → bull/bear researcher 토론 → trader → risk team → portfolio manager. "quick think"/"deep think" 2단 모델, provider 12곳+(v0.6.0). 시뮬레이션 거래소로만 주문. README가 스스로 "research scaffold", 발표 수치 재현 보장 없음. risk도 LLM agent라 하드 리밋 아님.
- **virattt/ai-hedge-fund**(~64k stars): 투자 대가 페르소나 agent + risk manager. paper/backtest만, 실행 전 사람 승인. "educational purposes only".
- **NoFxAiOS/nofx**: 아키텍처가 가장 실전형. LLM은 몇 분마다 제안만, **Go runtime이 하드 리밋으로 잘라냄** — 포지션 수·notional 상한, 레버리지 상한, 진입 직후 거래소 측 SL/TP, 수익 반납 시 자동 청산, 최소 보유·cooldown·시간당 진입 제한, 모델 반복 실패 시 신규 진입 차단 safe mode. OKX 포함 9개 거래소. 성과 주장 없음, "can lose money".
- **QuantDinger**: LLM 리서치 리포트 + Python 전략·백테스트·paper/live를 엮은 self-hosted "AI Trading OS". Jev 통합(Part A). 성과 근거 없음.
- **FinMem / FinAgent / FinRobot**: 학술. 원 논문은 짧은 기간·소수 종목으로 우위 보고 → FINSABER 20년·100+ 종목 재검증에서 우위 소멸(강세장 Sharpe B&H 0.61, FinAgent 0.12, FinMem −0.19, alpha p > 0.34).
- **온체인 agent (ElizaOS/ai16z, Coinbase AgentKit, GOAT, Solana Agent Kit)**: 지갑·액션 툴킷이지 전략 아님. AgentKit 문서는 spend cap·승인 게이트·목적지 allowlist가 없으니 개발자가 막으라고 명시. ai16z "AI 운용 VC"는 성과 입증 없이 토큰 시총 $2.4B → 2026-08 창업자가 후속 토큰을 "dead" 선언.

### B-2. 실전 대회와 벤치마크

- **Alpha Arena S1**(2025-10~11, 실제 $10k × 6, Hyperliquid perp, 동일 prompt): Qwen3 Max +22%, DeepSeek V3.1 +5%, 나머지 4개 손실, GPT-5 −60% 이상. Qwen 수수료만 ~$1,565.
- **Alpha Arena S1.5**(미국 주식, 8모델 × 4모드 = 32계좌, 2주): 6계좌만 플러스, 합계 −35.2%(−$112.6k / $320k). S1 우승 Qwen3 Max 4개 모드 전부 손실. Grok 4.20만 4개 모두 플러스(1회 관측). Nof1도 "statistical power is limited… run-to-run variation" 인정, 유의성 검정 없음.
- **StockBench**(arXiv 2510.02209): 대부분 equal-weight B&H(+0.4%) 미달, 최고 +2%(Kimi-K2, Qwen3-235B). 금융 QA 실력 ≠ 매매 실력.
- **LiveTradeBench**(arXiv 2511.03628, 21 LLM, 50일 live): LMArena 점수와 매매 성과 상관 주식 ρ≈0.05, Polymarket −0.38, 두 시장 간 Sharpe 상관 ≈0.
- **Look-Ahead-Bench**(arXiv 2601.13770): Llama 3.1, DeepSeek 3.2 등에서 뚜렷한 look-ahead bias.
- **EvolveTrade**(arXiv 2609.17632): system prompt를 policy로 자가 수정, 고정 prompt보다 "대부분 설정에서" 개선. 비용 차감 여부 불명, 비교 대상이 B&H 아님.
- **From Hypotheses to Factors**(arXiv 2604.26747): GPT-5.4는 factor 가설만, 고정된 deterministic 엔진이 split·비용·OOS 검증. 5bp 비용 Sharpe 1.55, 단 alpha가 소형·저유동성 토큰에 집중, OOS가 학습 cutoff와 겹칠 수 있음.

### B-3. 실패 유형

1. **Look-ahead / 기억**: Profit Mirage(2510.07920) — cutoff 이후 Sharpe 51–62% 하락, 입력을 크게 바꿔도 예측 82%가 그대로인 모델도.
2. **보고 품질**: Agentic Trading 서베이(2605.19337) — 실증 19편 중 비용 모델 명시 1편, survivorship 1편, 재현성 0편.
3. **Overtrading**: Alpha Arena 수수료 격차.
4. **비결정성**: 같은 모델 순위가 회차마다 뒤집힘(S1 → S1.5).
5. **조작·상태 오염**: TradeTrap(2512.02261) — 가짜 뉴스 주입 시 연환산 279.6% → 86.5%, 포트폴리오 77% 집중. NoFX 계열은 포지션 state 변조 시 −61% → **거래소 기준 대사가 없으면 치명적**.
6. **지시 위반·숫자 환각**: 한국 후기 "AI가 최소 주문금액 같은 제약을 어긴다".

### B-4. 한국 사례

- **조코딩**(o1-preview, 업비트): "약 2달 +35%" + 같은 글에서 "가만히 들고 있는 게 더 이득". 책·강의 마케팅 성격.
- **OKKY**(o3-mini, 59만원, ~1달): −11.56% vs 시장 −9.79%. ±7% 강제 청산을 직접 추가해도 오작동 잦음, "모든 결정을 AI에 맡기는 건 무리".
- velog 등은 API 비용 절감(캐싱) 이야기 위주, 수익 검증·백테스트 없음.

### B-5. 비교표

| 프로젝트 | LLM 역할 | Guardrails | 증거 품질 |
|---|---|---|---|
| TradingAgents | 분석·토론·최종 결정 전부 | LLM risk agent(소프트), 시뮬레이션 체결 | 낮음, 저자가 재현성 부인 |
| ai-hedge-fund | 페르소나 신호 → 결정 | 사람 승인, 실거래 없음 | 교육용 |
| NoFX | 몇 분마다 제안 | Go 하드 리밋·SL/TP·throttle·safe mode | 아키텍처 우수, 성과 근거 없음 |
| QuantDinger | 리서치 + 전략 보조 + Jev 관문 | paper 우선 | 마케팅 위주 |
| FinMem / FinAgent | timing 결정 | 없음 | 장기 재검증에서 반박 |
| ElizaOS / ai16z | 펀드 "결정" | 거의 없음 | 실패, 토큰 붕괴 |
| AgentKit / GOAT / SAK | 온체인 액션 | AgentKit spend cap 없음 명시 | 툴킷 |
| Alpha Arena S1 / S1.5 | 완전 자율 | 거래소 증거금만 | 실제 돈, n 작음, S1.5 합계 −35% |
| StockBench / LiveTradeBench | 일 단위 자율 | 벤치마크 | 중간, B&H와 비슷하거나 열위 |
| Factor agent (2604.26747) | 가설만 생성 | 고정 deterministic 평가 엔진 | 상대적 양호, 소형주 편중·cutoff 겹침 |

**마케팅 vs 증거**: "Qwen +22%", "조코딩 +35%", "ai16z AI 펀드"는 내러티브. 증거는 S1.5 합계 −35%, StockBench B&H 열위, FINSABER alpha 무유의, Profit Mirage cutoff 후 Sharpe 51–62% 하락.

### Sources (Part B)
github.com/TauricResearch/TradingAgents · github.com/virattt/ai-hedge-fund · github.com/NoFxAiOS/nofx · github.com/coinbase/agentkit · github.com/josejuarez96/tradepartner/pull/233 · /issues/230 · arxiv.org/abs/2601.13770 · arxiv.org/abs/2609.17632 · arxiv.org/abs/2510.07920 · arxiv.org/html/2605.19337v1 · arxiv.org/html/2512.02261v1 · arxiv.org/html/2604.26747v1 · okky.kr/articles/1528250 · threads.com/@youtubejocoding/post/DCp-2EeTc7g
스니펫만 참고(확인 강도 낮음): arxiv.org/abs/2510.02209 (StockBench) · arxiv.org/html/2511.03628v1 (LiveTradeBench) · arxiv.org/abs/2505.07078 (FINSABER) · iweaver.ai/blog/alpha-arena-ai-trading-season-1-results · forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament · coindesk.com/markets/2026/08/05/ai-agent-token-once-worth-usd2-4-billion-ends-with-founder-calling-it-dead · github.com/OpenByteInc/QuantDinger · arxiv.org/html/2405.14767v2 · solanacompass.com/projects/sendai
