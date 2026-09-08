# Claude Code + Codex Multi-Agent R&D Workspace 詳細設計書

**Version:** 1.2
**配布Repository:** `ai-rnd-framework`（R&D Engine の配布元）
**対象Repository:** Engine を `.claude/` に持つ任意の Git Repository（専用の `ai-rnd-workspace`、または既存の製品・サービス・インフラ Repository）
**Repository構成:** Workspace 1 つにつき単一Repository
**用途:** 汎用IT R&D Workspace

---

# 1. 目的

本システムは、単一のGit RepositoryをR&D Workspaceとして使用し、IT分野における様々なテーマを継続的に調査・検証・実装・評価するための基盤とする。Workspaceとは **R&D Engine（`.claude/`）とR&Dデータ（`.rnd/`）を持つGit Repository** であり、専用に用意した `ai-rnd-workspace` でも、既存の製品・サービス・インフラのRepositoryでもよい。

対象テーマは固定しない。

例:

* AWS
* Linux
* Kubernetes
* GPU
* NVIDIA
* LLM
* Claude Code
* Codex
* Database
* Network
* Security
* OSS
* 新製品
* 新サービス
* アーキテクチャ
* PoC

テーマごとにWorkspaceやRepositoryを作成しない。

代わりに、すべてのテーマを同一Repository配下の独立した **R&D Case** として管理する。

```text
ai-rnd-workspace
│
├── R&D Case 0001: Amazon Linux 2027
├── R&D Case 0002: NVIDIA PAIR
├── R&D Case 0003: Claude Code Agent Teams
├── R&D Case 0004: GPU PD Separation
└── ...
```

---

# 2. RepositoryとR&D Caseの役割

本設計では以下を明確に区別する。

## Framework / Workspace

`ai-rnd-framework` はR&D Engineの配布元Repositoryである。Engineは `.claude/` に閉じており、`rnd.py install` で任意のRepositoryへコピーされる。

WorkspaceはEngineを持つRepositoryであり、R&Dを行うための実行環境である。専用Repository（`ai-rnd-workspace`）として使う場合も、既存のRepositoryへ埋め込む場合も、Workspaceとしての構成と規則は同じである。

Workspaceは以下を保持する。

* Claude Code Agent
* Skill
* Hook
* Orchestrator
* Codex連携
* Policy
* Script
* Schema
* Shared Knowledge
* 全R&D Case
* R&D履歴

## R&D Case

R&D Caseは個々の話題を分離する単位である。

例えば、

```text
RND-20260907-001
Amazon Linux 2027 migration

RND-20260907-002
NVIDIA PAIR

RND-20260908-001
Claude Code Agent Teams
```

とする。

したがって、

```text
話題が違う
    ↓
Repositoryを分ける
```

のではなく、

```text
話題が違う
    ↓
R&D Caseを分ける
```

ものとする。

---

# 3. Repository方針

Repositoryは2種類に分かれる。

```text
ai-rnd-framework   Engineの配布元。R&Dデータを持たない。
<workspace>        Engineを持つRepository。R&Dデータ（Case・Knowledge）はここに蓄積する。
```

Workspaceは以下のどちらでもよい。

```text
専用Workspace   ai-rnd-framework のクローンをそのまま使う（旧来の ai-rnd-workspace）
埋め込み        既存の製品・サービス・インフラ Repository に rnd.py install で Engine を入れる
```

埋め込みの場合、EngineはそのRepositoryの `.claude/` と `.rnd/` にのみ存在し、Repository自身の `README.md`・`CLAUDE.md`・コードには触れない。Engineの運用マニュアルはEngine内（`.claude/rules/`）にあり、Repository固有の `CLAUDE.md` と共存する。

Workspaceの中では、

```text
aws-rnd
gpu-rnd
llm-rnd
```

のようなテーマ別Repositoryは作成しない。1つのWorkspaceのR&D成果は、そのWorkspaceの1Repositoryで管理する。

---

# 4. 基本Workflow

```text
User Question
      ↓
R&D Lead
      ↓
既存Case検索
      ↓
 ┌────┴─────┐
 │          │
既存        新規
 │          │
Case再開   Case作成
 └────┬─────┘
      ↓
Independent Research
      ↓
Critic / Counter Evidence
      ↓
Experiment Design
      ↓
Implementation
      ↓
Codex Independent Review
      ↓
Claude Fix
      ↓
Codex Re-review
      ↓
Review Convergence
      ↓
Validation
      ↓
Decision
      ↓
Case Archive
      ↓
Future R&Dから再利用
```

---

# 5. 基本原則

1. ResearcherとCriticを分離する。
2. BuilderとReviewerを分離する。
3. Claudeが実装したコードをCodexが独立レビューする。
4. Codex FindingをClaude自身の判断だけではCloseしない。
5. Claude修正後は必ずCodexへ戻す。
6. Codex Findingが収束するまでReview Loopを継続する。
7. Codex Reviewerはコードを変更しない。
8. Builder自身に最終PASS判定をさせない。
9. Workspace上のCaseファイルをSingle Source of Truthとする。
10. 会話履歴だけにR&D状態を依存しない。
11. 過去Caseは再利用するが、最新情報として無条件に信用しない。
12. EvidenceとAIによる解釈を分離する。
13. Repositoryそのものはテーマごとに分割しない。

---

# 6. Repository構成

Workspace（任意のRepository）の構成:

```text
<workspace>/
│
├── (Repository自身のファイル: README.md, CLAUDE.md, コード ... Engineは触れない)
├── .gitignore            (生成物 3 ファイルの除外行を rnd.py install が追加)
│
├── .claude/              R&D Engine
│   ├── VERSION
│   ├── settings.json     (既存があればマージ)
│   ├── rnd-policy.json
│   ├── pytest.ini
│   │
│   ├── agents/
│   │   ├── researcher.md
│   │   ├── critic.md
│   │   ├── claim-verifier.md
│   │   ├── experiment-designer.md
│   │   ├── builder.md
│   │   ├── isolated-builder.md
│   │   ├── codex-reviewer.md
│   │   └── validator.md
│   │
│   ├── skills/
│   │   ├── rnd-orchestrator/
│   │   │   └── SKILL.md
│   │   ├── rnd-case/
│   │   │   └── SKILL.md
│   │   ├── review-convergence/
│   │   │   └── SKILL.md
│   │   └── knowledge-promotion/
│   │       └── SKILL.md
│   │
│   ├── hooks/
│   │   ├── safety-gate.py
│   │   ├── builder-write-guard.py
│   │   └── reviewer-shell-guard.py
│   │
│   ├── rules/
│   │   ├── rnd.md
│   │   ├── review.md
│   │   └── rnd-manual.md
│   │
│   ├── scripts/
│   │   ├── rnd.py
│   │   ├── rnd_doctor.py
│   │   ├── codex_review.py
│   │   ├── review_gate.py
│   │   ├── safety_check.py
│   │   ├── generate_index.py
│   │   └── rndlib.py
│   │
│   ├── schemas/
│   │   ├── case.schema.json
│   │   ├── evidence.schema.json
│   │   ├── findings.schema.json
│   │   ├── experiment.schema.json
│   │   └── codex-review-output.schema.json
│   │
│   └── tests/
│
└── .rnd/                 R&D データ
    ├── index.json        (生成物)
    ├── INDEX.md          (生成物)
    │
    ├── knowledge/
    │   ├── shared/
    │   ├── candidates/
    │   └── catalog.json  (生成物)
    │
    └── cases/
        ├── RND-20260907-001-topic-a/
        ├── RND-20260907-002-topic-b/
        └── ...
```

配布Repository `ai-rnd-framework` は上記に加えて `README.md`・`SPEC.md`・`CLAUDE.md`・`CHANGELOG.md`・`LICENSE`・`.codex/config.toml` を持つ。これらはFramework自身の文書・設定であり、Workspaceへはインストールされない。

`.claude/` は配布元からコピーされるが、コピーされた時点でそのWorkspaceの正式な構成要素である。

**Engine（`.claude/`）とR&Dデータ（`.rnd/`）はWorkspaceのRepositoryでGit管理する。** Engineの更新は `rnd.py install --upgrade` で配布元から取り込む。

---

# 7. Agent Architecture

```text
                         User
                          │
                          ▼
                     R&D Lead
                 Main Claude Code
                          │
                 R&D Orchestrator
                          │
           ┌──────────────┴──────────────┐
           ▼                             ▼
      Researcher                       Critic
      最大3並列                       最大2並列
           │                             │
           └──────────────┬──────────────┘
                          ▼
                Experiment Designer
                          │
                          ▼
                       Builder
                       Claude
                          │
                          ▼
                    Codex Review
                          │
                ┌─────────┴─────────┐
                │                   │
             Finding              CLEAN
                │                   │
                ▼                   │
           Claude Fix               │
                │                   │
                ▼                   │
              Tests                 │
                │                   │
                └────────► Codex ◄──┘
                              │
                        Convergence
                              │
                              ▼
                         Validator
                              │
                              ▼
                           Lead
                              │
                              ▼
                         R&D Case
```

---

# 8. Agent一覧

| Agent               | 主責務                   |      Write |
| ------------------- | --------------------- | ---------: |
| R&D Lead            | Case統括・最終判断           |   管理ファイルのみ |
| Researcher          | 最新技術調査                |         No |
| Critic              | 反証・独立検証               |         No |
| Claim Verifier      | 個別Claim再検証            |         No |
| Experiment Designer | 実験設計                  |         No |
| Builder             | PoC・コード実装             |        Yes |
| Codex Reviewer      | Codex CLIレビュー         | Review成果のみ |
| Validator           | Acceptance Criteria検証 |         No |

---

# 9. R&D Case

各話題は必ずCaseとして保存する。

```text
rnd/
├── RND-20260907-001-amazon-linux-2027/
├── RND-20260907-002-nvidia-pair/
├── RND-20260908-001-claude-agent-teams/
└── ...
```

同じ話題の続きであれば新しいCaseを作らず、既存Caseを再開する。

---

# 10. Case内部構造

```text
rnd/RND-20260907-002-nvidia-pair/
│
├── case.json
├── brief.md
├── handoff.md
│
├── research/
│   ├── synthesis.md
│   ├── evidence.json
│   └── sources.md
│
├── experiments/
│   ├── EXP-001/
│   │   ├── plan.md
│   │   ├── manifest.json
│   │   ├── result.md
│   │   └── logs/
│   └── EXP-002/
│
├── reviews/
│   ├── round-01/
│   ├── round-02/
│   └── ...
│
├── validation/
│   ├── result.json
│   └── result.md
│
├── artifacts/
│
└── decision.md
```

---

# 11. Case検索

新規ユーザー要求を受けた場合、Leadは必ず先に既存Caseを検索する。

検索対象:

* title
* tags
* keywords
* decision
* synthesis
* 全文

```text
User Question
      ↓
index.json
      ↓
全文検索
      ↓
Similar Case?
 ┌────┴────┐
YES        NO
 │          │
Resume     Create
```

---

# 12. Case ID

形式:

```text
RND-YYYYMMDD-NNN
```

例:

```text
RND-20260907-001
RND-20260907-002
RND-20260908-001
```

---

# 13. Case状態

```text
NEW
 ↓
TRIAGE
 ↓
RESEARCHING
 ↓
DESIGNING
 ↓
EXPERIMENTING
 ↓
BUILDING
 ↓
REVIEWING
 ↓
VALIDATING
 ↓
DECIDED
 ↓
ARCHIVED
```

例外:

```text
BLOCKED
FAILED
FAILED_TO_CONVERGE
INCONCLUSIVE
STALE
```

状態はClaude会話ではなく、

```text
case.json
```

を正式情報とする。

---

# 14. Case再開

新しいClaude Code Sessionからでも、

```bash
python scripts/rnd.py resume RND-20260907-002
```

で再開可能とする。

出力:

```text
Current State
Research Summary
Experiment Status
Open Codex Findings
Validation Status
Last Action
Next Action
```

これにより、

```text
Claude Session
```

と、

```text
R&D Case lifetime
```

を分離する。

---

# 15. Research Phase

Standard Caseでは、

```text
Researcher A
→ Official Documentation

Researcher B
→ GitHub / Issues / Releases

Critic
→ Counter Evidence
```

を並列実行する。

必要に応じて最大:

```text
Researcher × 3
Critic × 2
```

まで並列化する。

---

# 16. Research Knowledge

Researcherが発見した最新仕様そのものをAgent Memoryへ保存しない。

保存先:

```text
rnd/<CASE>/research/
```

とする。

理由:

* 技術情報は陳腐化する
* Evidence provenanceが必要
* AgentごとのKnowledge差異を防ぐ
* 将来の再検証が必要

---

# 17. Experiment Phase

調査だけでは判断できない場合、

```text
Experiment Designer
```

が実験を定義する。

各Experimentには、

```text
Hypothesis
Environment
Procedure
Expected result
Failure condition
Acceptance criteria
Evidence
```

を定義する。

---

# 18. Builder

Builderは承認された実験または実装だけを実施する。

変更前にBaseline Testを実行する。

```text
Before
A PASS
B FAIL
C PASS

After
A PASS
B FAIL
C PASS
```

のように、既存Failureと新規Failureを区別する。

---

# 19. Parallel Build

複数案を比較する場合のみWorktreeを利用する。

```text
Alternative A → Worktree A
Alternative B → Worktree B
Alternative C → Worktree C
```

これはWorkspace分割ではない。

すべて同じ `ai-rnd-workspace` Repository内の一時的なGit Worktreeとして扱う。

最終的なR&D記録は同一Caseへ統合する。

---

# 20. Codex Review

コード変更を伴ったCaseではCodex Reviewを必須とする。

基本:

```text
Claude Builder
      ↓
Codex Reviewer
```

Codex ReviewerはClaudeによるレビューAgentではない。

```text
Claude wrapper
      ↓
Codex CLI
      ↓
Codex model
```

として動作する。

---

# 21. Codex Review Convergence Loop

```text
Builder
   ↓
Tests
   ↓
Codex
   ↓
Findings?
 ┌─┴───────────┐
YES             NO
 │               │
Claude Fix       │
 │               │
Tests            │
 │               │
 └──────► Codex ─┘
            ▲
            │
           Loop
```

Claudeの修正後は必ずCodexへ戻す。

---

# 22. Review終了条件

Standard:

```text
Codex actionable findings = 0
AND
Required tests = PASS
```

High Risk:

```text
Codex CLEAN
↓
Codex CLEAN
↓
Required tests PASS
```

2回連続Cleanを要求可能とする。

---

# 23. Finding状態

```text
open
fixed_pending_review
confirmed_fixed
disputed
false_positive
accepted_risk
```

通常:

```text
open
 ↓
Claude Fix
 ↓
fixed_pending_review
 ↓
Codex Review
 ↓
confirmed_fixed
```

Claudeだけでは `confirmed_fixed` に変更できない。

---

# 24. Review最大反復

標準:

```text
maxRounds = 5
```

5回で収束しない場合:

```text
FAILED_TO_CONVERGE
```

としてLeadへ戻す。

強制PASSは禁止する。

---

# 25. Oscillation Detection

以下の状態を検出する。

```text
Finding A
 ↓ fix
Finding B
 ↓ fix
Finding A 再発
```

同じFindingが繰り返し再発する場合:

```text
REVIEW_OSCILLATION
```

としてLeadへEscalateする。

---

# 26. Validator

Codex ReviewとValidatorは別目的とする。

Codex:

```text
Code Correctness
```

Validator:

```text
Behavior Correctness
Acceptance Criteria
Reproducibility
```

したがって、

```text
Codex CLEAN
```

だけではCase完了としない。

---

# 27. Knowledge構成

Repository共通知識:

```text
knowledge/shared/
```

昇格候補:

```text
knowledge/candidates/
```

Case固有知識:

```text
rnd/<CASE>/
```

とする。

---

# 28. Knowledge Promotion

Caseから得られた情報を自動でShared Knowledgeへ入れない。

```text
Case Finding
    ↓
Validated
    ↓
Reusable?
    ↓
Candidate
    ↓
Review
    ↓
knowledge/shared/
```

---

# 29. Freshness

Evidenceには、

```text
created
retrievedAt
lastVerified
freshnessClass
```

を持たせる。

Freshness Class:

```text
fast-moving
normal
stable
```

例:

```text
Claude Code
Codex
AWS新機能
LLM Runtime
Kubernetes最新版

→ fast-moving
```

期限切れの場合、過去Caseを参考にしつつ最新一次情報を再確認する。

---

# 30. ResearchとDecisionの分離

必ず、

```text
research/synthesis.md
```

と、

```text
decision.md
```

を分ける。

例えば、

```text
Research:
技術的には実現可能。

Decision:
今回の用途では採用しない。
```

を区別する。

---

# 31. Shared KnowledgeとCase Archive

本Repositoryでは時間とともに以下が蓄積される。

```text
ai-rnd-workspace/
│
├── knowledge/
│
└── rnd/
    ├── RND-0001
    ├── RND-0002
    ├── RND-0003
    ├── RND-0004
    └── ...
```

これ自体がWorkspaceのKnowledge Baseとなる。

---

# 32. Agent Memory

Agentごとの永続Knowledge Baseは原則として使用しない。

優先順位:

```text
Case Knowledge
>
Shared Workspace Knowledge
>
Agent Memory
```

とする。

Agentには主として、

```text
仕事のやり方
```

を定義する。

最新技術情報はCaseへ保存する。

---

# 33. Git管理対象

以下はWorkspaceの同じRepositoryでGit管理する。

```text
.claude/      R&D Engine
.rnd/         R&D History + R&D Knowledge
```

つまり、

```text
R&D Engine
+
R&D History
+
R&D Knowledge
```

のすべてを1Repositoryで管理する。生成物（`.rnd/index.json`・`.rnd/INDEX.md`・`.rnd/knowledge/catalog.json`）だけは管理対象外とし、`rnd.py doctor` が再生成する。

---

# 34. Repositoryを分ける条件

通常の話題変更ではRepositoryを分けない。

Repository分離を検討するのは、例えば以下の場合のみとする。

* Security Boundaryが異なる
* 機密レベルが異なる
* 異なるGit履歴を維持する必要がある

R&D対象が製品Repositoryそのものである場合、Workspaceを分ける必要はない。Engineをその製品Repositoryへ埋め込み（§3）、Caseをその中で管理してよい。その場合もSecurity Boundaryは保たれる。Builderが書けるのはCase成果物（`protectedPaths.builderAllowed`）だけであり、製品コードはPolicyで明示的に開放しない限り書き込み対象にならない（§37）。

専用Workspaceで検証した結果を実製品へ導入する場合は、製品Repository側で別作業を行う。これは「話題を分ける」ためではなく、

```text
コードベースとSecurity Boundaryを分ける
```

ためである。

---

# 35. 外部Repositoryとの連携

将来的に別Repositoryのコードを調査対象にする場合も、`ai-rnd-workspace` のCase管理は維持する。

例:

```text
ai-rnd-workspace
│
└── RND-0052
      │
      └─ 対象: production-service repository
```

Caseには対象Repository情報を記録する。

```json
{
  "targetRepository": "production-service",
  "targetCommit": "abc123..."
}
```

ただし外部Repositoryのコードそのものを `ai-rnd-workspace` へコピーして恒久管理することは原則行わない。

---

# 36. Concurrency

標準最大:

```text
6 Agents
```

例:

```text
Researcher Official ─┐
Researcher GitHub ───┼ parallel
Researcher External ─┤
Critic A ────────────┤
Critic B ────────────┘
```

実装比較時:

```text
Builder A ─┐
Builder B ─┼ parallel
Builder C ─┘
```

並列処理はR&D Case内部の処理であり、Repository分割とは無関係とする。

---

# 37. Safety Boundary

Researcher:

```text
Read only
```

Critic:

```text
Read only
```

Codex Reviewer:

```text
Read only
```

Validator:

```text
Read / Test only
```

Builder:

```text
Case成果物のみ Write allowed
```

Builderが書けるのは `.claude/rnd-policy.json` → `protectedPaths.builderAllowed` に列挙されたパスと一時ディレクトリだけである。既定では、

```text
.rnd/cases/<CASE>/artifacts/
.rnd/cases/<CASE>/experiments/EXP-*/logs/
/tmp
```

それ以外、すなわち

```text
.claude/            R&D Engine
.rnd/knowledge/     Shared Knowledge
.rnd/cases/<CASE>/  の管理ファイル（case.json, research/, reviews/, validation/ ...）
Repository自身のコード（Engineを埋め込んだ場合）
```

は既定で書き込み禁止である。つまりR&D実装Agent自身がR&D基盤のルールを書き換えられず、EngineをホストするRepositoryのコードもCaseの副作用で変更されない。製品コードの一部をBuilderに書かせたい場合は、そのパスを `builderAllowed` に追加して明示的に開放する。

---

# 38. R&D Orchestrator

Main Claude Code SessionをLeadとし、

```text
rnd-orchestrator
```

SkillがWorkflowを制御する。

役割:

```text
Case検索
Case作成
Risk判定
Research分解
Parallel dispatch
Synthesis
Experiment dispatch
Builder dispatch
Codex Review Loop
Validator dispatch
Decision
Archive
```

---

# 39. Single Source of Truth

以下の優先順位とする。

```text
case.json
    ↓
Case artifacts
    ↓
Evidence
    ↓
Shared Knowledge
    ↓
Claude conversation
```

Claudeの会話履歴はR&D状態の正式記録ではない。

---

# 40. Repositoryの成長モデル

本Repositoryは、

```text
初期:
RND-0001

↓

半年後:
RND-0050

↓

数年後:
RND-0500
```

のようにR&D Caseが蓄積されることを前提とする。

Case数が増えた場合でもRepositoryをテーマ別に分割するのではなく、まず、

```text
index
tags
search
archive
semantic search
```

で対応する。

---

# 41. Semantic Search

初期Versionでは不要とする。

Case数が増加した場合、

```text
title
tags
keywords
full-text grep
```

から、

```text
embedding
semantic retrieval
```

へ拡張する。

Repository分割は検索性能対策としては行わない。

---

# 42. 最終Repository構成

Workspaceは以下の1Repositoryである（専用Repositoryでも、Engineを埋め込んだ既存Repositoryでも同じ）。

```text
<workspace>/
│
├── (Repository自身のファイル)
│
├── R&D Engine
│   └── .claude/
│
└── R&D Data
    └── .rnd/
        ├── knowledge/      Shared Knowledge
        └── cases/          R&D History
            ├── RND-0001
            ├── RND-0002
            ├── RND-0003
            └── ...
```

概念的には、

```text
            <workspace>
                 │
       ┌─────────┼─────────┐
       │         │         │
       ▼         ▼         ▼
   R&D Engine  Knowledge  R&D Cases
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
             AWS          GPU          LLM
             Case         Case         Case
```

である。

AWS、GPU、LLMはRepositoryではなくCaseである。

---

# 43. 完了条件

Research Case:

```text
Research complete
Critic complete
Evidence recorded
Decision recorded
```

Experiment Case:

```text
Research complete
Experiment executed
Codex CLEAN if code changed
Validation recorded
Decision recorded
```

Implementation Case:

```text
Required Tests PASS
Codex Review Convergence PASS
Validator PASS
No unresolved blocking Finding
Decision recorded
```

---

# 44. Git Repository名

配布Repository名:

```text
ai-rnd-framework
```

Description:

> Multi-agent AI workspace for technical R&D, experimentation, review convergence, validation, and reusable knowledge.

専用Workspaceを作る場合の推奨名は `ai-rnd-workspace`。既存Repositoryへ埋め込む場合、Repository名は変えない。

---

# 45. 最終設計原則

本設計では、

```text
Repository
```

は、

```text
R&Dという活動そのもの
```

を表す。

一方、

```text
R&D Case
```

は、

```text
個々の話題
```

を表す。

したがって、

```text
AWS
GPU
Claude
Codex
Kubernetes
Linux
```

のようにテーマが変化してもWorkspaceは変更しない。

```text
<workspace>
       │
       ├── Case A
       ├── Case B
       ├── Case C
       └── Case D
```

として継続的に知識とEvidenceを蓄積する。

本Repositoryの最終成果物はAIとの会話ではなく、

```text
Evidence
+
Reproducible Experiment
+
Reviewed Implementation
+
Validated Result
+
Documented Decision
+
Accumulated R&D Knowledge
```

である。
