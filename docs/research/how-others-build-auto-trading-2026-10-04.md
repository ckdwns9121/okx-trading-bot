# 남들은 자동매매를 어떻게 만들고, 실제로 돈이 되는가 — 리서치 노트 (2026-10-04)

> 목적: 모든 전략을 걷어낸 상태(태그 `archive/legacy-strategies-2026-10-04`)에서 새 전략을 설계하기 전에,
> 오픈소스·리테일·한국 커뮤니티·프로/학계 네 갈래가 **무엇을 어떻게 하고 결과가 어땠는지**를 증거 중심으로 정리한다.
> 선행 문서 `trading-bot-feature-landscape-2026.md`(봇 인프라 표준 기능)와 `funding-carry-okx-2026-10-04.md`(펀딩 캐리 부정 결과)를 잇는다.
>
> 범례: **[증거]** 수치·논문·공식 문서가 있는 내용 / **[일화]** 후기·댓글 등 검증 불가 사례. 네 파트는 각각 별도 조사로 작성됐고, Part 0은 그 공통분모를 뽑은 종합이다.

---

## Part 0. 종합 — 네 갈래가 한목소리로 말하는 것

### 1. 리테일 알고 트레이딩의 기본 결과는 "손실"이고, 범인은 전략이 아니라 비용과 빈도다

질 높은 증거(대규모 계좌 데이터, 비용 반영, 생존편향 통제)는 전부 같은 방향이다. 대만 데이트레이더 80%+ 손실, 브라질 선물 300일 이상 지속자 **97% 손실**, EU CFD 리테일 71~89% 손실 **[증거]**. 크립토 쪽 "97%가 잃는다" 류 숫자는 출처 불명 재인용이 많아 인용하지 않지만, 실무 커뮤니티(QuantConnect·Blind·클리앙·디시)의 합의는 일관된다: *"비용 후 매수-보유를 이기는 건 극히 어렵다", "수수료가 최종 수익의 절반을 갉아먹는다"*.

네 파트 모두에서 손실의 1차 원인은 **거래 빈도**다. 분·시간봉 전략은 거의 예외 없이 수수료·슬리피지에 진다. Rob Carver의 "speed limit"(비용에 pre-cost Sharpe의 1/3 이상 쓰지 말 것)을 리테일 계좌에 적용하면 보유 기간이 **수 주 단위**로 나온다. 한국 커뮤니티가 변동성 돌파(일 1회)로도 "횡보장에서 수수료에 죽는다"고 결론낸 것, 우리가 지운 변동성 돌파(1h)가 +9% 수익에 수수료 $544였던 것은 같은 현상이다.

### 2. 거래소와 SaaS가 파는 봇(그리드·DCA·카피)은 알파가 아니라 변동성 수확 + 마케팅이다

그리드는 횡보장 전용, 추세장에서 인벤토리를 깔고 죽거나 상승분을 거의 다 놓친다(독립 백테스트 MDD 30~58%). DCA/마팅게일은 승률이 높고 손실이 극단적으로 비대칭이다. 카피 트레이딩은 팔로워 수익자 48.5%, 리더 drawdown 70% 사례가 흔하다 **[증거: 업계 조사]**. 거래소 리더보드는 "Best PnL" 정렬 + 7일 drawdown만 보여 주는 전형적 생존편향 전시다. **이쪽은 연구 대상이 아니다.**

### 3. 증거가 있던 엣지들도 빠르게 압축되고 있다

| 엣지 | 상태 | 리테일 접근 |
|---|---|---|
| 크로스 섹션 모멘텀(1~4주) | 확립됐으나 쇠퇴 중. 알파가 **숏 레그와 강세장**에 집중 | 롱 온리·대형 코인 한정이면 부분적 |
| 타임시리즈 모멘텀 / 추세 | 논쟁 중. 2020-07 이후 음(-)이라는 재검증 있음. 낙폭 개선의 대부분이 **변동성 스케일링** 효과 | 가능하나 단일 자산은 통계적으로 증명 불가(트레이드 수 부족) |
| 펀딩/베이시스 캐리 | 2020~25 Sharpe 6.45 → 2025 음수. OKX는 공식상 0.01%에 고정 | 우리 선행 리서치와 일치: **보류** |
| 마켓메이킹 / 센티먼트 첫 수분 | 기관 영역 | **불가** (레이턴시·자본) |
| 온체인 신호 | OOS에서 반복 실패, 인과 방향이 가격→지표 | 데이터는 열려 있으나 증거 빈약 |
| 소형 코인 유동성 공급 프리미엄 | 조건부 확립 | 용량 제약이라 대형 자본은 못 들어옴 — 리테일 몫이지만 toxic flow 위험 |

발표된 이상현상은 발표 후 평균 58% 쇠퇴(McLean–Pontiff), 크립토는 더 빠르다(2020~22 알파 36.2% → 2023~24 13.5%) **[증거]**.

### 4. 그래도 살아남는 소수의 공통점은 "전략"이 아니라 "구조"다

네 파트가 독립적으로 같은 목록을 냈다.
1. **단순한 규칙 여러 개를 결합**해 낮은 Sharpe를 분산으로 올린다 (Grinold: `IR = IC × √Breadth`). 복잡한 단일 시스템보다 단순한 것이 살아남는다.
2. **보유 기간이 길고 회전율이 낮다** — 주/월 단위 리밸런싱. 한국의 진지한 퀀트 커뮤니티(강환국·『파이썬 증권 데이터 분석』·퀀트 쿡북)가 전부 동적자산배분·듀얼모멘텀·팩터로 간 이유.
3. **변동성 목표 사이징**이 기본값이다. 추세추종의 낙폭 개선은 진입 규칙보다 여기서 나온다.
4. **승격 게이트 + 통계적 겸손**: 시도 횟수를 기록하고(DSR, MinBTL), 사전에 통과 기준을 적고, OOS → 페이퍼 → 소액 순. "파라미터를 만질 때마다 통할 확률이 낮아진다."
5. **리스크 관리가 곧 전략**: drawdown 상한, 킬스위치, 대사, TCA로 전략 decay와 체결 품질 분리.
6. 생계가 아니라 **보조 수입/지적 취미**로 접근 — 전업 선언 집단의 성적이 가장 나쁘다 **[증거: 브라질·대만]**.

### 5. 리테일이 구조적으로 유리한 자리는 셋뿐이다

(a) **용량 제약 전략** — 소형 알트는 큰 자금이 들어갈 수 없다. (b) **느린 전략** — 수 주 보유에서는 기관의 레이턴시 우위가 무의미하다. (c) **커리어 리스크 부재** — 3년 drawdown을 견딜 수 있는 건 상환 압력이 없는 개인뿐이다(정량 증거는 아니고 실무 상식). 반대로 레이턴시·데이터·금융(숏 차입, 수수료 티어)에서는 우위가 전혀 없다. 학술 모멘텀의 절반(숏 레그)은 리테일에게 닫혀 있다.

### 6. 이 프로젝트에 대한 결론

**기대치.** 현실적인 목표는 "매수-보유보다 더 번다"가 아니라 **"매수-보유보다 훨씬 덜 깨지면서 비슷하게 번다"**(위험 조정 우위)다. 네 파트 모두 그 이상을 약속하는 증거를 내놓지 못했다. 지웠던 Donchian이 바로 그 범주였다는 점도 기록해 둔다 — 문제는 그 전략이 "쓰레기"여서가 아니라, 공개 캔들 하나만 보고 단일 자산을 타이밍하는 자리에 서 있었다는 것이다.

**다음 전략의 형태는 네 조사가 공통으로 가리킨다.**
- 입력: 일봉, **여러 종목 동시**(횡단면) — 단일 자산 trend는 통계적으로 증명이 불가능하므로 자산 수로 유효 표본을 키운다(Chan).
- 규칙: 단순한 모멘텀/추세 규칙 **2~3개의 가중 결합**, 롱 온리, BTC 레짐 필터(약세장 전체 현금).
- 사이징: **변동성 목표** + R 기반 포지션 크기. 레버리지 1배.
- 빈도: **주 1회** 리밸런싱, 회전율 상한을 Carver 1/3 규칙으로 먼저 계산.
- 검증: 시도 횟수 장부, 이웃 파라미터 안정성(±20%), 비용 2~3배 시나리오, 사전 등록 통과 기준, 페이퍼 6~12개월 또는 트레이드 30~50건.
- 이것은 앞서 후보 3번(크로스 섹션 모멘텀)에 해당한다. 후보 2번(청산 캐스케이드 역추세)은 데이터가 없으므로 수집기를 켜 두고 기다린다.

**인프라에서 더 채울 것**(새 전략이 생겼을 때, Part 1 갭 분석 기준): 미체결 타임아웃·긴급 시장가 전환을 담당하는 Executor/주문 상태기계, **거래소 측 stop 주문**(봇이 죽어도 손절은 살아 있게), 시작 시 fill 복원·외부 주문 감지를 포함한 지속 대사, 연속 손절/낙폭 기반 **쿨다운 후 자동 재개**(Freqtrade Protections), look-ahead 자동 검출, R 기반 사이징 헬퍼, 전략에서 분리된 포지션 관리(Triple Barrier). 반대로 OMS/EMS 분리·코로케이션·풀 VWAP는 베끼지 않는다.

**한국 거주자 리스크(Part 3).** OKX는 FIU 미신고 거래소다. 2026-01 구글플레이 앱 차단, 트래블룰 전 거래 확대 예정, 2027-01부터 가상자산 소득 22% 분리과세. 당장 API 사용이 막힌 건 아니지만 **거래소 선택 자체가 전략만큼 중요한 변수**가 됐다. 장기 운용을 전제한다면 국내 거래소(업비트/빗썸) 또는 한국투자증권 KIS API(주식·ETF) 대안을 한 번은 검토해야 한다 — 이 결정은 코드가 아니라 사용자 몫이다.

---

## Part 1. 오픈소스 자동매매 프레임워크 아키텍처

### 프레임워크별 요약

**Freqtrade** (Python, ~53–55k stars, 월 단위 캘린더 릴리스, GPL-3)
- 구조: 단일 프로세스 루프 → 오픈 트레이드 조회 → OHLCV 다운로드 → 페어별 전략 콜백 → 주문 상태/타임아웃 처리 → stoploss/ROI/시그널 exit → 신규 entry. 전략은 pandas DataFrame 위에서 벡터화로 지표를 계산하지만 봇 자체는 캔들 단위로 도는 하이브리드.
- 전략 추상화: `populate_indicators / populate_entry_trend / populate_exit_trend` + `custom_stoploss`, `custom_exit`, `custom_stake_amount`, `confirm_trade_entry/exit`, `adjust_trade_position`(DCA·부분청산), `check_entry/exit_timeout`.
- 리스크: 정적/트레일링 stoploss, `stoploss_on_exchange`, `minimal_roi`, `max_open_trades`, `unfilledtimeout` + `emergency_exit`. **Protections** 플러그인(StoplossGuard, MaxDrawdown, LowProfitPairs, CooldownPeriod)이 서킷브레이커 역할. Pairlist 체인으로 유니버스 관리.
- dry-run: 가상 지갑, 호가창 기반 체결(최대 5% 슬리피지 가정). `lookahead-analysis` 커맨드가 look-ahead bias를 자동 탐지.
- 대상: 추세/스윙·DCA 류 시그널 전략. FreqAI로 ML 내장.
- 비판: 암호화폐 전용, 설정 난이도, 캔들 OHLC 기반이라 체결 모델이 거칠다는 평.

**Hummingbot** (Python+Cython, ~19–20k stars, v2.17.0 2026-09, Apache-2)
- 구조: Connectors(50+ CEX/DEX) ↔ 전략. V2: **Controller → Executor → Connector** 3계층.
- 전략 추상화: `StrategyV2Base`, Controller, Executor(PositionExecutor, GridExecutor, Arbitrage, DCA). PositionExecutor는 **Triple Barrier**(SL / TP / 시간제한 + 트레일링)를 설정 객체로 받아 포지션을 스스로 마감.
- 리스크: 글로벌 `kill_switch_rate`(계좌 가치 변동 % 기준 자동 정지), 인벤토리 스큐, `*_paper_trade` 커넥터.
- 대상: 마켓메이킹(PMM, Avellaneda-Stoikov), 크로스 거래소 MM, 차익거래, 그리드.
- 비판: 터미널 UI, 설정 복잡, 백테스트가 약함(MM 중심).

**Jesse** (Python, ~8.6k stars, MIT 코어)
- 구조: `should_long/should_short → go_long/go_short → should_cancel_entry → update_position` 이벤트 드리븐. 멀티 타임프레임·멀티 심볼을 look-ahead 없이 지원한다고 명시.
- 전략 추상화: `self.buy = (qty, price)`, `self.stop_loss`, `self.take_profit` 선언 → 엔진이 주문 유형 자동 결정. **`risk_to_qty(capital, risk_per_capital, entry, stop)`가 1급 헬퍼**.
- 라이브/페이퍼는 유료 플러그인.
- 비판: 커뮤니티 작음, 라이브 유료.

**NautilusTrader** (Rust 코어 + Python, ~29.6k stars, 2.0.0rc5 2026-09, LGPL-3)
- 구조: `NautilusKernel`이 MessageBus, Cache, DataEngine, **ExecutionEngine, RiskEngine**, Portfolio를 조립. 단일 스레드 결정론. 백테스트·샌드박스·라이브가 **같은 커널**, 어댑터만 교체. crash-only + 외부 supervisor.
- 리스크: RiskEngine 사전 검증(정밀도, min/max notional, reduce-only 위반, 잔고, 레이트) → `OrderDenied`. **TradingState: ACTIVE / REDUCING / HALTED** 3단계.
- 리컨실리에이션: 시작 시 주문/포지션을 거래소 리포트와 정렬(fill 복원, 외부 주문 감지), 이후 in-flight·open order·position 지속 체크. `trade_id` 중복 체결 방지.
- 비판: 학습 곡선 가파름, ML 미내장, 2.0 전환기.

**QuantConnect Lean** (C# 코어 / Python·C#, ~22k stars, Apache-2)
- Algorithm Framework: Universe Selection → Alpha(`Insight`) → Portfolio Construction → **Risk Management** → Execution 5단계. 내장 Risk 모델(MaximumDrawdownPercentPerSecurity, TrailingStop 등), Execution 모델(Immediate/VWAP/StdDev).
- 비판: C# 코어 노출, 클라우드 비용, 무거움. 멀티 자산군이 강점.

**OctoBot** (Python, ~6.7k stars) — Evaluator → Strategy → Trading Mode 3단계, 비동기 채널, CCXT. 그리드/DCA/TA/TradingView 웹훅/LLM. 초보 친화 대신 백테스트 정밀도 약함.

**Backtrader** (유지보수 중단) / **vectorbt** (벡터화 파라미터 스윕, 라이브 없음, look-ahead는 사용자 책임, 신기능은 유료 PRO).

**CCXT** (~44k stars, MIT) — 100+ 거래소 통합 API. 대부분의 봇이 이 위에 구축. 한계: 거래소별 `params`가 새어 나오고 세부 의미론은 결국 거래소 문서를 봐야 함.

### 비교표

| 프레임워크 | 언어 | Stars(약) | 실행 모델 | 전략 추상화 | 리스크/킬스위치 | 리컨실 | 페이퍼 | 주 전략 유형 |
|---|---|---|---|---|---|---|---|---|
| Freqtrade | Py | 53k+ | 루프+DataFrame | populate_* 콜백 | Protections, 온익스체인지 SL | DB 중심, 약함 | dry-run 지갑 | 추세/DCA, ML |
| Hummingbot | Py/Cython | 20k | 이벤트(틱) | Controller→Executor | kill_switch_rate, Triple Barrier | 커넥터 내 | *_paper_trade | MM/차익/그리드 |
| Jesse | Py | 8.6k | 캔들 이벤트 | should_*/go_* | risk_to_qty, SL/TP 1급 | 미확인 | 유료 | 방향성 |
| NautilusTrader | Rust+Py | 29.6k | 결정론 이벤트 | Actor/Strategy 핸들러 | RiskEngine, TradingState 3단계 | 시작+지속 | Sandbox | 범용 |
| Lean | C#/Py | 22k | 이벤트 | 5-모듈 Framework | Risk Model 교체형 | 브로커리지 플러그인 | 페이퍼 브로커 | 포트폴리오 |
| OctoBot | Py | 6.7k | 비동기 채널 | Evaluator→TradingMode | TradingMode 내 SL | CCXT 의존 | 시뮬레이터 | 그리드/DCA |
| vectorbt | Py/Numba | 9.3k | 벡터화 | from_signals | 없음 | 없음 | 없음 | 파라미터 스윕 |

### "교과서적" 봇의 공통 형태

1. Exchange adapter 계층으로 거래소 차이 격리 → 2. Data 계층(확정 봉만 전달) → 3. **Strategy 계층은 순수 로직** → 4. **Sizing/Risk 계층이 전략과 분리**되어 주문 의도를 검증·조정 → 5. Execution 계층이 주문 상태기계·타임아웃·재시도·긴급 청산 담당 → 6. 동일 코드로 backtest → paper → live → 7. 전역 정지 장치.

좋은 프레임워크가 하고 자작 봇이 흔히 빠뜨리는 것: 주문 상태기계 + **지속적 대사**(fill 복원, 외부 주문 감지, 중복 fill 방지), **단계적 정지**(REDUCING), **포지션 관리 전담 객체**(Triple Barrier), look-ahead **자동** 검출, **R 기반 사이징 1급 API**, **거래소 측 stoploss**, crash-only + supervisor.

### 우리 스택과의 대조

**이미 갖춘 것**: RiskGate 사전 검증(Nautilus RiskEngine과 동형), 파일 영속 KillSwitch(fail-closed, reduce-only 허용 → REDUCING 유사), reconciliation(불일치 시 트립), **TCA 로그**(대부분의 OSS에도 없는 장점), look-ahead-free 백테스트 설계 원칙, 순수 전략/러너 분리, demo 모드 강제.

**부족한 것**: Executor/주문 상태기계(미체결 타임아웃·긴급 시장가), 거래소 측 stop 주문, 시작 시 fill 복원·외부 주문 감지, Protections급 쿨다운 자동 재개, look-ahead 자동 검출 도구, R 기반 사이징 헬퍼, 전략과 분리된 포지션 관리.

---

## Part 2. 리테일 알고 트레이더가 실제로 돌리는 전략과 수익성 증거

### 전략 유형별 정리

| 전략 | 필요한 regime | 주 blow-up 모드 | 증거 품질 |
|---|---|---|---|
| Grid | 횡보 + 적당한 변동성 | 범위 이탈 후 inventory 깔고 하락; 상승장은 B&H 대비 크게 underperform | 중간 (독립 백테스트 1건, 리더보드는 생존편향) |
| DCA / Martingale | 완만한 하락 후 반등 반복 | 안전주문 소진 → 미실현 손실 고정 or 패닉 청산 | 약함 (벤더 블로그·일화) |
| Market making (Hummingbot) | 낮은 adverse selection | 추세일 하루에 몇 주치 spread 반납 | 약함 (리텐션 기반 간접 추정) |
| Funding / basis carry | 양(+) funding 지속 | funding 부호 반전, perp leg 청산, counterparty | 강함 (학술), 단 2025년부터 압축 |
| Cross-exchange arb | 괴리 ≥ 수수료+이체비용 | latency 열위, 부분체결 | 중간 |
| Trend following | 장기 추세 | V자 whipsaw, turnover 비용 | 중간~강함 (학술 긍정, 실무는 vol-scaling 효과가 대부분) |
| Mean reversion (BB/RSI) | 좁은 range | 추세 돌파 시 역방향 누적 | 약함 (백테스트 다수 음수) |
| ML / LLM 신호 | 신호 > 비용 | 비용 미반영, 과적합, 높은 turnover | 중간 (pre-registered 1건: 전부 no-go) |
| Copy trading | 리더의 운 지속 | 리더 drawdown 70%, copy-lag | 약함~중간 |

- **Grid**: Binance 4년 시간봉 독립 백테스트 — 폭락장에서 B&H보다 덜 잃었지만 강세장 상승분을 거의 다 놓침, MDD 30~58%. Pionex류 15~50% APR은 "매일 같은 수익 1년 지속" 가정. **volatility harvesting이지 alpha가 아니다.**
- **DCA/Martingale**: 승률 높고 손실 극단 비대칭. 안전주문 소진 후 "수개월 수익을 한 번에 지우는" 손실 확정.
- **Market making**: Hummingbot 자체 분석($ONE Makers) — 68명 중 상위 10명이 체결량 88%, 1개월 뒤 40% 잔존. 실제 PnL 미확인을 스스로 인정.
- **Funding carry**: Borri–Liu–Tsyvinski–Wu(2025) 2020~25 Sharpe 6.45 → 2024 이후 4.06 → **2025 음수**. 우리 선행 리서치와 일치.
- **Cross-exchange arb**: 메이저 괴리는 4초 안에 닫힘, 거래당 0.1~0.3%. 리테일(100~500ms)은 느린 괴리만, ~8% 부분체결로 평균 0.3% 손실.
- **Trend following**: 2017~2025 실무 백테스트 — B&H CAGR 73.5%/MDD −84% vs trend 6.3%/−15%, Sharpe 신뢰구간 0.1~1.5(데이터 부족). 낙폭 개선 대부분이 vol-scaling. **"덜 잃는" 전략이지 "더 버는" 전략이 아니다.**
- **ML/LLM**: pre-registered LightGBM 실험 — AUC 0.55 실재 신호, 그러나 4개 심볼 모두 net 수익 기준 미달. LLM 에이전트는 일 turnover 49~101%, net Sharpe −4.7~−11.2. 대부분 논문이 비용 0 가정.
- **Copy trading**: 팔로워 수익자 48.5%, MEXC 합산 −21만 USDT, 리더 drawdown 70% 흔함 **[증거: 업계 90일 조사]**.

### 리테일 수익성의 솔직한 증거 **[증거]**

- Barber–Odean(2000): 가계 계좌 시장 하회 — "trading is hazardous to your wealth".
- 대만 데이트레이더(Barber–Lee–Liu–Odean): 6개월 단위 80%+ 비용 후 손실.
- 브라질 선물(Chague 등): 300일 이상 지속자 **97% 손실**, 최저임금 이상 1.1%.
- ESMA/FCA CFD: 리테일 71~89% 손실.
- 크립토 특정 증거는 약함. "CoinGecko 97%" 류는 출처 불명. FCA 2021 설문은 오히려 자기보고 66% 수익(강세장 시점). 실무 합의: "비용 후 B&H를 이기는 건 극히 어렵다", "99% 알고리즘에 bias가 있어 백테스트를 믿을 수 없다".

### 공통 실패 패턴

1. **과적합** — Freqtrade: 0.001보다 정밀한 hyperopt 파라미터는 보통 과적합. QuantConnect Alpha Market 수백 개 중 PSR 80% 유지 약 10개.
2. **비용·슬리피지 무시** — 왕복 10~20bp가 일봉 시스템에서 연 25~50%p drag. 전략이 발화하는 변동성 급등 순간이 호가가 가장 얇은 순간.
3. **백테스트 체결 가정** — 캔들 내 high가 먼저 온다고 가정한 트레일링 스탑은 실거래와 다르게 체결(Freqtrade #2662).
4. **look-ahead** — `shift(-1)`, 생존 코인만 테스트, forward-fill 공백.
5. **레버리지 + 인프라** — 2025-10-10 폭락 6시간 $19B·160만 계좌 청산, Binance 과부하; 2025-04 AWS 장애; 2025-08-29 Binance Futures 18분 주문 불가. **봇은 이런 순간 reduce-only조차 못 낼 수 있다.**

### 지속 성공을 보고하는 소수의 공통점

(a) 단순 전략 여러 개 결합 (b) 낮은 turnover·긴 보유 (c) OOS → 장기 페이퍼 → 소액 승격 게이트 + 통계적 겸손 (d) risk management가 곧 전략 (e) 생계가 아닌 보조 수입/취미.

---

## Part 3. 한국 커뮤니티의 비트코인·주식 자동매매 실태

### 지배적 전략: 래리 윌리엄스 변동성 돌파(VB)

조코딩 유튜브 + `pyupbit`가 "국민 튜토리얼". `youtube-jocoding/pyupbit-autotrade`(★251)에 기본 VB, 15일 이평 필터, Prophet, k 최적화, 백테스트가 들어 있다 **[증거]**. 이유: 일봉 1개, 코드 10줄, `목표가 = 시가 + (전일 고가−저가)×k`, 익일 09:00 전량 매도. 2017~21 상승장 백테스트가 화려.

그 다음: 이동평균·볼린저·슈퍼트렌드·돈치안(클리앙 시스템트레이딩), 그리드(선물 거래소 내장), **AI(LLM) 매매**(2024~25 조코딩 GPT/o1 강의, 한빛미디어 출간), 김프/선물-현물 차익(대부분 "불가능/위험"으로 귀결), 주식은 KIS API로 ETF 적립·공모주 자동청약 등 "귀찮음 제거" 자동화.

### API·라이브러리와 고충 **[증거]**

| 영역 | 주로 쓰는 것 | 제약 |
|---|---|---|
| 업비트 | `pyupbit`(★571), 공식 REST | 주문 초당 8회·분당 200회, 시세 IP당 10/s; 429 누적 시 418 차단. 수수료 0.05% |
| 빗썸 | `pybithumb`, 조코딩 `python-bithumb` | 문서 빈약 |
| 해외 | `python-binance`, `ccxt` | **2026-01-28부터 구글플레이가 FIU 미신고 거래소 앱(바이낸스·OKX·바이비트·MEXC) 차단.** 웹/API는 동작하나 법적 회색지대 |
| 키움 OpenAPI+ | PyQt5 + COM | Windows 전용, 32bit, 로그인 수동, 클라우드 불가 → 2024 REST 출시로 완화 중 |
| 한국투자증권 KIS | 공식 `open-trading-api`(★1.6k) | 유일하게 운영과 동일한 모의투자, 리눅스/맥 OK, 국내+해외 단일 API |
| LS증권 / 대신 Creon | REST / CybosPlus | Creon은 HTS 종료 시 끊김, 32bit |

추세: **키움 OpenAPI+ → KIS REST**("맥/리눅스 서버에 24시간").

### 수익 후기 vs 손실 후기

**[증거]에 가까운 것:**
- 조코딩 AI 매매(o1-preview) 2개월 **+35%** — 본인이 "가만히 들고 있는 게 더 이득"이라고 인정. 후속: o3-mini +1.54%, deepseek-r1 −3.09%.
- OKKY 후기(o3-mini, 1개월): 전략 **−11.56%** vs 단순보유 −9.79% → 시장보다 더 잃음.
- 코인픽 VB: 백테스트 +1100%(2017~20) 주장, 같은 글 제목이 "−35만원 손실 인증".
- 브런치 OMG/KRW 6주: HPR 86.95%. **"나는 견딜 수 있는 MDD를 과대평가했다."**

**[일화]**: 클리앙 3년 코인봇("수익 괜찮음", 교훈: 남의 돈 운용 말 것·백테스트가 전부·안 되는 구간 버티기), 2022 VB+볼린저+슈퍼트렌드+돈치안 묶음(승률 40%대, 손익비로 우상향), 디시 "횡보장에서 잦은 손절로 수수료가 많이 깨진다. **수수료가 최종 수익의 절반**".

**수렴한 결론:** ① 수수료에 다 먹힘(분봉 VB·그리드) — 실전 전환 시 CAGR 20~30% 감소, 샤프 반토막, MDD 1.5~2배 ② 횡보장에서 죽음(VB) / 추세장에서 죽음(그리드) ③ k 최적화는 과최적화 ④ **심리적 MDD** — 거의 모든 손실 후기가 "내가 못 버텼다"로 끝남 ⑤ 2024~25 강세장 후기는 "그냥 들고 있는 게 나았다".

### 진지한 퀀트 커뮤니티는 무엇을 다르게 하나

- 강환국 『할 수 있다! 퀀트 투자』: 자산배분, **동적자산배분(듀얼모멘텀·VAA·LAA)**, 월 1회 리밸런싱, 소형주 멀티팩터. "단타 봇이 아니라 월 1회 기계적 리밸런싱".
- 『파이썬 증권 데이터 분석』(김황후): 웹스크래핑→DB→백테스트→API까지 전 과정. 전략보다 "데이터 파이프라인을 직접 만드는 법".
- 『파이썬을 이용한 퀀트 투자 포트폴리오 만들기』(이현열): 팩터 종목선정 + API 리밸런싱 자동화.
- 공통 차별점: ① 거래 빈도를 월/주 단위로 ② 종목 선정·자산군 비중이 알파, 타이밍은 보조 ③ 모의투자 2~4주+ → 소액 ④ 백테스트는 "발견"이 아니라 "기각" 도구.

| 전략 | 가르치는 곳 | 보고된 전형적 결과 |
|---|---|---|
| 변동성 돌파(일봉, k≈0.5) | 조코딩/pyupbit, 코인픽, 블로그 다수 | 백테스트 연 30~50% 주장, 실전 승률 40~50%·긴 손실 구간·"수수료 반토막" **[일화 多]** |
| VB+이평 / 돈치안·슈퍼트렌드 묶음 | 클리앙 | 2022 하락장 우상향 주장, 수치 미공개 **[일화]** |
| 그리드 | 거래소 내장 | 횡보 소폭 수익, 추세 전환 시 손실 **[일화]** |
| LLM 매매 | 조코딩 2024~25 | +35%(강세장) vs −11.6%(약세장) — 시장 방향 종속 **[증거]** |
| 김프 차익 | 블라인드·펨코 질문글 | "불가능/자금세탁 조사 위험" **[증거: 규제]** |
| 동적자산배분·듀얼모멘텀·팩터 | 강환국, 퀀트 쿡북 | 장기 CAGR 10~15% 주장, 공개 실전 수치는 단편 **[일화]** |

### 규제·실무 맥락 **[증거]**

- 가상자산이용자보호법 2024-07-19 시행 — "펌핑 감지" 류 전략은 시세조종 가담 리스크로 재해석될 수 있음.
- 트래블룰: 2026-08 보도 기준 **전 거래로 확대** 예정, 해외거래소·개인지갑 이전은 위험도별 차등·고위험 금지.
- 해외거래소: 2026-01-28 구글플레이 앱 차단. 외국환거래법상 1회 5천 달러·연 5만 달러 초과 송금 증빙 → 김프 차익의 자금 왕복 경로가 법적으로 막힘.
- 세금: 가상자산 소득 **2027-01-01부터 기타소득 분리과세 22%**(연 250만 원 초과분). 고빈도 봇은 손익 계산용 거래기록 보존이 필수.
- 김프: 2024~25년 2~5%로 압축, 2026 초 역프도 발생.

---

## Part 4. 프로 시스템 트레이딩 vs 리테일 봇: 구조적 차이와 엣지의 증거

### 시스템 펀드가 일을 구조화하는 방식

**연구 파이프라인은 통계적 검증 절차다.** López de Prado(Bailey et al.): 백테스트는 다중 비교 문제. N개 변형을 시도하면 노이즈에서도 `E[SR_max] ≈ √(2·log N / T)`. Minimum Backtest Length `MinBTL ≈ (2·log N)/SR²` — 45개 변형 시도 후 Sharpe 1.0을 "발견"했다면 약 20년치 일간 데이터가 필요. 권고: (1) 시도 횟수 기록·보고 (2) Deflated Sharpe Ratio (3) 분석 전 stopping rule 문서화. Harvey–Liu–Zhu(RFS 2016): 유의성 문턱 t > 3.0. **리테일이 가장 자주 빠뜨리는 것이 "몇 번 시도했는가"의 기록이다.**

**포트폴리오 구성: 여러 약한 비상관 신호.** Grinold `IR = IC × √Breadth`. Carver(*Systematic Trading*): 여러 규칙의 forecast 가중평균, 상관 0.95 이상 변형은 추가 안 함, 백테스트 Sharpe의 1/4~1/3을 깎아 기대치.

**리스크 버짓팅.** 연 변동성 목표를 먼저 정하고 역산해 포지션 사이징(volatility targeting), Kelly의 절반 이하. drawdown limit·kill switch는 전략 밖 운영 규칙 — 이 저장소 RiskGate와 같은 접근.

**실행과 비용: speed limit.** *기대 pre-cost Sharpe의 1/3 이상을 비용에 쓰지 말라.* 리테일 선물 계좌 예시 결론: 6~7주 보유. 기관은 TCA(implementation shortfall)와 square-root impact `I ≈ Y·σ·√(Q/V)`로 알파 감소가 신호 붕괴인지 실행 악화인지 분리.

**인프라.** Man AHL: "모델 변경보다 새 시장·데이터 탐색이 더 가치". 구체적 incubation 기간은 비공개.

### 크립토 고유 엣지의 증거

| Edge | Evidence | Retail? |
|---|---|---|
| Cross-sectional momentum (1~4주) | 확립, 쇠퇴 중. Liu–Tsyvinski–Wu(JF 2022) 3-factor; 2주 모멘텀 t=3.89, post-2020 t=3.70. 12·24주는 무의미. 알파는 **숏 레그·강세장** 집중, 거래비용 큼 | 롱 온리·대형 한정 부분적 |
| Time-series momentum | 논쟁. Liu–Tsyvinski(RFS 2021) 강한 TSMOM vs 2016~23 재검증(Arefev) 0과 구별 불가, 2020-07 이후 음 | 가능하나 트레이드 수 부족 |
| Funding / basis carry | 확립, 급속 쇠퇴. Sharpe 6.45 → 4.06 → 2025 음 | 프리미엄 압축; 우리 결과와 일치 |
| Size / volume anomaly | 약함. 마이크로캡만 | 실현 불가 |
| Liquidity provision / ST reversal | 조건부 확립(Bianchi 등). 소형·고변동 페어 집중, adverse selection 보상 | 패시브 리밋은 toxic flow |
| Market making (HFT) | 확립(기관). Wintermute/Jump 60+ 베뉴 ms 조정 | **불가** |
| Variance risk premium | 중간. BTC VRP ≈ 0.14, S&P ~2%보다 큼 | 숏 볼 꼬리 위험, 제한적 |
| On-chain | 약함/반증. OOS 반복 실패, 인과 가격→지표 | 증거 빈약 |
| Sentiment | 혼재. 첫 1시간(3분) 내 효과 집중 | HFT 영역 |

**발표 후 쇠퇴**: McLean–Pontiff OOS 26%, 발표 후 58% 감소. 크립토 2020~22 알파 36.2% → 2023~24 13.5%, 횡단면 분산 38% 붕괴. **비용이 결론을 바꾸는 방식**: 거래소 간 차익 "모든 거래소" 주 0.685% → 실제 접근 가능 시장 주 0.038%.

### 리테일의 구조적 우위와 열위

우위: 용량 제약 전략(헤지펀드 95%가 자산 13%만 보유), 느린 전략(수 주 보유에선 레이턴시 무의미), 커리어 리스크 부재. 열위: 레이턴시, 데이터(틱·오더북), 금융(숏 차입, 교차 마진, 수수료 티어). 모멘텀 알파가 숏 레그에 집중 → 리테일은 "학술 모멘텀"의 절반만 접근.

### 솔로 개발자가 채택할 검증 관행

1. **시도 횟수 장부** — 모든 파라미터 조합·변형을 세고 DSR로 보정.
2. **최소 백테스트 길이** — Sharpe SE ≈ `√((1+0.5·SR²)/N)`. 일간 10년, SR 0.5면 95% 구간 −0.1~1.1. **단일 자산 일간 trend는 통계적으로 증명 불가** → 자산 수를 늘려 유효 표본을 키움(Chan).
3. **트레이드 수** — 100건 미만이면 결론 금지. 일간 Donchian 55/20은 10년에도 수십 건.
4. **Walk-forward + 이웃 안정성** — (p±20%, q±20%)에서 급락하면 과적합.
5. **비용 모델** — maker/taker, 체결률, impact, 펀딩. 비용 2~3배에서도 양(+).
6. **사전 등록 통과 기준** — 백테스트 전에 "OOS Sharpe ≥ X, MaxDD ≤ Y, 트레이드 ≥ Z, 비용 2배 시 양(+)" 적어 두고 결과 보고 안 바꿈.
7. **페이퍼/데모 기간** — "기대 트레이드 30~50건" 또는 레짐 전환 1회 포함; 일간 trend면 6~12개월. TCA로 체결 품질과 신호 품질 분리.

확립: 다중 검정 보정 필요성, 비용이 소형 알파를 지움, 횡단면 모멘텀의 과거 존재, 캐리 압축. 논쟁 중: TSMOM 현재 유효성, 모멘텀 쇠퇴 원인(학습 vs 구조 변화), 온체인·센티먼트 수익화.

---

## Sources

### Part 1
- https://www.freqtrade.io/en/stable/bot-basics/ · /plugins/ · /stoploss/ · /configuration/ · /lookahead-analysis/
- https://github.com/freqtrade/freqtrade/releases/tag/2026.4
- https://hummingbot.org/strategies/ · /strategies/v2-strategies/executors/positionexecutor/ · /client/global-configs/kill-switch/ · /client/global-configs/paper-trade/ · /release-notes/2.12.0/
- https://github.com/hummingbot/hummingbot
- https://docs.jesse.trade/docs/strategies/ · /strategies/entering-and-exiting.html · /utils.html · /livetrade.html · https://github.com/jesse-ai/jesse
- https://nautilustrader.io/docs/latest/concepts/architecture/ · /execution/ · /strategies/ · /live/ · https://github.com/nautechsystems/nautilus_trader/releases
- https://github.com/QuantConnect/Lean · https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview
- https://github.com/Drakkar-Software/OctoBot · /wiki/Developer-Guide
- https://www.backtrader.com/docu/concepts/ · https://github.com/mementum/backtrader · https://github.com/polakowo/vectorbt · https://github.com/ccxt/ccxt
- https://autotradelab.com/blog/nautilus-vs-vectorbt-vs-freqtrade-20-python-quant-trading-frameworks-compared · https://gainium.io/compare/freqtrade-vs-hummingbot · https://greyhoundanalytics.com/blog/vectorbt-vs-backtrader/

### Part 2
- https://dev.to/aduenasdev/i-backtested-the-most-popular-binance-grid-bots-on-4-years-of-real-data-1gnb
- https://uwuu.ai/blog/pionex-review · https://www.pionex.com/blog/can-explain-to-me-what-the-apr/ · https://blockresearch.ai/blog/dca-bot
- https://hummingbot.org/blog/does-community-based-market-making-work/
- https://arxiv.org/pdf/2510.14435 (Borri, Liu, Tsyvinski, Wu)
- https://hftadvisory.substack.com/p/cross-exchange-arbitrage-and-the · https://summitward.com/learn/crypto-trend-following
- https://github.com/Hassnat07/crypto-ml-backtest · https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7498983
- https://repository.essex.ac.uk/25396/1/copy%20trading%20experiment_32ms%20final.pdf · https://yieldfund.com/is-copy-trading-profitable-a-90-day-multi-exchange-study
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101 (Chague, De-Losso, Giovannetti)
- https://faculty.haas.berkeley.edu/odean/papers/day%20traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf · https://www.umass.edu/preferen/You%20Must%20Read%20This/Barber-Odean%202011.pdf
- https://www.esma.europa.eu/node/84933 · https://brokerrank.net/research/retail-loss-rates · https://www.fca.org.uk/publications/fca-research/research-note-cryptoasset-consumer-research-2021
- https://www.quantconnect.com/forum/discussion/5720/realistic-expectations-in-algo-trading/ · /15725/ · /12017/
- https://www.teamblind.com/post/is-solo-algotrading-a-waste-of-time-sb54cz7f
- https://github.com/freqtrade/freqtrade/issues/2662 · /issues/8518
- https://www.fticonsulting.com/insights/articles/crypto-crash-october-2025-leverage-met-liquidity · https://www.datawallet.com/crypto/october-10-crypto-crash-explained
- https://fortune.com/crypto/2025/04/15/binance-crypto-exchanges-amazon-web-services-aws-outage/ · https://thecurrencyanalytics.com/altcoins/traders-frustrated-as-binance-futures-experiences-temporary-downtime-193488

### Part 3
- https://github.com/youtube-jocoding/pyupbit-autotrade · https://github.com/sharebook-kr/pyupbit · https://github.com/sharebook-kr/pybithumb · https://github.com/koreainvestment/open-trading-api
- https://github.com/chaeso/upbitbot · https://github.com/hunmin815/autoTrade · https://github.com/tofulim/auto_trade · https://github.com/didw/quant_trading
- https://docs.upbit.com/kr/reference/rate-limits · https://algolab.co.kr/blog/kr-broker-api-comparison · https://pluscoach.co.kr/blog/kiwoom-rest-api-python-guide-2026.html · https://wikidocs.net/165185
- https://www.clien.net/service/board/cm_vcoin/16089574 · /18084474 · /17435783
- https://gall.dcinside.com/board/view/?id=bitcoins_new1&no=9394043 · https://okky.kr/articles/1528250 · https://coinpick.com/daily_quant/7528 · https://brunch.co.kr/@9ilwonkim/35 · https://steemit.com/kr/@yoon/682bb3
- https://x.com/youtubejocoding/status/1859786348389073375 (스니펫 기준) · https://m.hanbit.co.kr/store/books/book_view.html?p_code=B5063161940
- https://m.yes24.com/Goods/Detail/90578506 · https://m.yes24.com/goods/detail/45504859 · https://hyunyulhenry.github.io/quant_cookbook/ · https://breakingcube.com/퀀트-투자를-두-달간-직접-해보니/
- https://www.teamblind.com/kr/post/김프-이용하면-무위험-차익거래-가능한거-아님-bPBrZaM7 · https://dealsite.co.kr/articles/76717
- https://www.fntimes.com/html/view.php?ud=202608111436025202a735e27af_18 · https://www.asiae.co.kr/article/2026051109524277542 · https://zdnet.co.kr/view/?no=20260115093947 · https://www.fsc.go.kr/no010101/82682 · https://view.asiae.co.kr/en/article/2026071508024489681 · https://www.spotedcrypto.com/kimchi-premium-guide-2026/

### Part 4
- https://www.nber.org/papers/w25882 · https://www.nber.org/papers/w24877 (Liu, Tsyvinski, Wu)
- https://arxiv.org/html/2510.14435v2 · https://ideas.repec.org/a/eee/finana/v94y2024ics1057521924001509.html · https://ideas.repec.org/p/cer/papers/wp730.html
- https://papers.ssrn.com/sol3/Delivery.cfm/7405060.pdf?abstractid=7405060 (Arefev, 스니펫) · https://link.springer.com/article/10.1007/s11408-025-00474-9 (스니펫) · https://github.com/prams2104/crypto-momentum-backtest
- https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf (MinBTL) · https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 (DSR) · https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314 (Harvey–Liu–Zhu)
- https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365 (McLean–Pontiff)
- https://www.cxoadvisory.com/big-ideas/a-few-notes-on-systematic-trading/ · https://qoppac.blogspot.com/2020/04/how-fast-should-we-trade.html · https://qoppac.blogspot.com/2025/11/r-squared-and-sharpe-ratio.html (Carver)
- https://www.robeco.com/en-int/insights/2018/04/fundamental-law-of-active-management-shows-way-to-higher-information-ratio
- https://www.slideshare.net/slideshow/enhancing-statistical-significance-of-backtestsby-dr-ernest-chan-managing-member-of-qts-capital-management-llc/75641423
- https://thehedgefundjournal.com/man-ahl-marks-30-years/ · https://thehedgefundjournal.com/ahl-evolution/ · https://thehedgefundjournal.com/capacity-in-the-hedge-fund-industry/
- https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing
- https://arxiv.org/pdf/2410.15195 · https://www.pm-research.com/content/iijaltinv/23/4/84 (VRP)
- https://arxiv.org/html/2606.00071v1 (on-chain OOS) · https://link.springer.com/article/10.1007/s12525-025-00815-6 · https://www.etd.ceu.edu/2023/zhumagaziyev_sh.pdf
- https://multicoin.capital/2026/02/17/adverse-selection-rules-everything-around-me/ · https://insights4vc.substack.com/p/inside-jump-crypto-13b-terra-trade · https://crypto.news/wintermute-sec-broker-dealer-crypto-market-maker-stocks/
- https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Trading-Cost.pdf (Frazzini, Israel, Moskowitz)

### 접근 제한 표기
SSRN·Springer·ResearchGate·ScienceDirect 일부 1차 자료는 403으로 검색 스니펫 수준 인용. Backtrader 스타 수는 소스마다 15k~23k로 상이. Jesse 라이브 플러그인 가격은 2차 소스. "CoinGecko 97%" 류 수치는 원출처 미확인으로 본문에서 제외.
