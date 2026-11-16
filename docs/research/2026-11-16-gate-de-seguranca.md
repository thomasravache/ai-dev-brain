# Pesquisa: gate de segurança para o `gluon-spec`

Data da pesquisa: 16/11/2026. Versões de ferramentas conferidas na API de releases do GitHub nessa data. Fontes primárias sempre que possível; quando uma afirmação vem de fonte secundária, isso está indicado.

---

## 0. Resumo executivo

- **O mercado convergiu em quatro ideias:**
  1. Segurança começa no **design**, com threat modeling leve por feature. Veja o [OWASP Threat Modeling Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html) e a [CISA Secure by Design](https://www.cisa.gov/securebydesign).
  2. Classes inteiras de vulnerabilidade são eliminadas com **APIs e frameworks seguros por construção**, e não por varredura. Veja o [Google Safe Coding](https://research.google/pubs/safe-coding-rigorous-modular-reasoning-about-software-safety/).
  3. A **cadeia de suprimentos** virou risco de primeira linha. Ela entrou como A03 no [OWASP Top 10:2025](https://top10.owasp.org/2025/0x00_2025-Introduction/), e os próprios scanners foram atacados: [trivy-action em março de 2026](https://www.aquasec.com/blog/trivy-supply-chain-attack/).
  4. Gates automáticos só funcionam com **baixo falso positivo e bloqueio só do que é novo**. Veja o [Google, CACM 2018](https://cacm.acm.org/magazines/2018/4/226371-lessons-from-building-static-analysis-tools-at-google/pdf) e o [Semgrep diff-aware](https://semgrep.dev/docs/semgrep-ci/findings-ci).
- **O `gluon-spec` já tem metade da infraestrutura:** um `security_scan` no G5, um checklist no G4 e os pilares `segredos-dados`, `seguranca-acesso` e `dependencias`.
- **Faltam quatro coisas:**
  - (a) um lugar na spec para **ameaças e testes de abuso**;
  - (b) separar o scan por **camada**, com política de bloqueio;
  - (c) baselines para **segurança de aplicação web/API**, **proteção contra abuso** e **integridade de build e supply chain**;
  - (d) regras para **agentes e LLM**, tanto no produto quanto no próprio processo SDD, que é multiagente.
- **Mapeamento natural dos perfis:** `minimo` ≈ ASVS L1, `padrao` ≈ ASVS L2 e `rigoroso` ≈ ASVS L3. O próprio [ASVS 5.0](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x03-What-is-the-ASVS.md) descreve esses níveis assim:
  - L1 é "o mínimo", cerca de 20% dos requisitos;
  - L2 é o nível que "a maioria das aplicações deveria buscar";
  - L3 serve a quem precisa demonstrar o nível mais alto, como bancos.

---

## 1. Ponto de partida: o que o `gluon-spec` já tem

| Onde | Hoje | Lacuna |
|---|---|---|
| G4 (`references/gates.md`) | Item de qualidade: "no secrets or sensitive data in code or logs" | Não há checklist de segurança estruturado (acesso, injeção, sessão, SSRF) nem exigência de teste de acesso negado no G4. Isso só aparece no ADR `seguranca-acesso`. |
| G5 | `security_scan` único, opcional, em `sdd-config.yml`. Exemplos: `npm audit`, `gitleaks` | Um comando só mistura SAST, SCA e segredos. Não há política de severidade, "só novos achados" ou supressão com prazo. |
| G6 | `smoke_test` e E2E no ambiente | Nenhuma verificação de segurança no ambiente implantado: headers, cookies, DAST passivo, verificação de assinatura ou proveniência do artefato. |
| Pilar `segredos-dados` (mínimo) | Segredos fora do repositório, varredura no CI, mascaramento de log testado, rotação | Bom. Falta: varredura antes do commit e no histórico, e resposta a vazamento (revogar, e não só rotacionar). |
| Pilar `seguranca-acesso` (padrão) | Autenticação centralizada, negar por padrão, menor privilégio, expiração e revogação, teste de acesso negado | Falta: cookies e sessão (atributos, prefixo `__Host-`, regeneração), CSRF e matriz de autorização (IDOR/BOLA). |
| Pilar `dependencias` (padrão) | Varredura de vulnerabilidade (crítico bloqueia), lockfile, EOL, licenças | Falta a supply chain moderna: pinning de actions por SHA, cooldown de versão nova, pacote malicioso ou typosquatting, SBOM, assinatura e proveniência. |
| Pilar `desempenho-escala` (rigoroso) | "Limites e quotas para proteger o sistema de picos e abuso" | Anti-abuso só aparece no perfil rigoroso. Pelo [OWASP API4:2023](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/), limites de payload, paginação e timeouts são básicos e valem para qualquer API. |
| Template de spec | NFRs, Mapa de Comportamentos e Plano de Testes | Não existe seção de ameaças nem prefixo de teste de segurança. |

---

## 2. Frameworks e padrões de referência

### 2.1 Quadro geral

| Referência | Versão atual | O que exige do time de dev | Verificável por máquina | Exige julgamento humano |
|---|---|---|---|---|
| **OWASP Top 10** | **2025**, anunciado como final em [nov/2025](https://www.theregister.com/2025/11/11/new_owasp_top_ten_broken/). Lista em [top10.owasp.org/2025](https://top10.owasp.org/2025) | É um documento de **conscientização** e não um padrão verificável. Serve como checklist de revisão e de threat modeling. | Parcial: injeção, configuração e componentes vulneráveis (SAST, SCA, IaC) | A01 acesso, A06 design inseguro, A10 condições excepcionais e lógica de negócio |
| **OWASP ASVS** | **5.0.0** (maio/2025), [repo](https://github.com/OWASP/ASVS). Próxima: 5.0.1 | Requisitos testáveis em 17 capítulos (V1 Encoding … V17 WebRTC) e níveis L1, L2 e L3. Recomenda um ASVS "sob medida" a partir do L1 ([seção "How to use"](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x03-What-is-the-ASVS.md)) | Boa parte: headers, cookies, TLS, configuração e cripto, via testes e DAST | V2 lógica de negócio, V8 autorização (modelo) e V15 arquitetura |
| **OWASP API Security Top 10** | **2023**, ainda vigente ([lista](https://api-security.owasp.org/editions/2023/en/0x11-t10)) | BOLA (API1), autorização por propriedade (API3), consumo de recursos (API4), autorização por função (API5), fluxos de negócio sensíveis (API6), SSRF (API7), inventário (API9) | API4 (limites testáveis), API8 (configuração), API9 (inventário via OpenAPI) | API1, API3, API5 e API6 dependem do modelo de autorização e do negócio. Viram **testes escritos pelo time**. |
| **OWASP Top 10 for LLM Applications** | **2025** ([lista](https://genai.owasp.org/llm-top-10/)) | LLM01 prompt injection, LLM02 vazamento, LLM05 saída sem tratamento, LLM06 agência excessiva, LLM10 consumo ilimitado | LLM05 (encoding da saída), LLM10 (limites) e varredura de segredos em prompts | LLM01 e LLM06: desenho de permissões |
| **OWASP Top 10 for Agentic Applications** | **2026**, publicado em 09/12/2025 ([página](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)) | ASI01 sequestro de objetivo, ASI02 mau uso de tools, ASI03 abuso de identidade e privilégio, ASI04 supply chain agêntica, ASI05 execução inesperada de código, ASI06 envenenamento de memória e contexto, ASI07 comunicação insegura entre agentes, ASI08 falhas em cascata, ASI09 exploração da confiança humana, ASI10 agentes fora de controle (nomes conforme [resumo da Speakeasy](https://www.speakeasy.com/blog/owasp-agentic-top-10-explained)). Princípios: *least agency* e *strong observability* (fontes secundárias) | Allowlist de tools, escopo de credenciais e sandbox são configuração e podem ser checados | O desenho de quais tools cada agente tem |
| **OWASP MCP Top 10** | **Beta, v0.1** ([projeto](https://owasp.org/projects/mcp-top-10)) | Servidores MCP "sombra", injeção e vazamento de contexto | Ainda instável: use como referência, não como gate | — |
| **NIST SSDF (SP 800-218)** | **1.1** (fev/2022) é a versão final. A **1.2 (Rev. 1)** está em rascunho desde 17/12/2025 e o comentário fechou em 30/01/2026 ([CSRC](https://csrc.nist.gov/pubs/sp/800/218/r1/ipd)). O perfil de IA é o [SP 800-218A](https://csrc.nist.gov/projects/ssdf/publications). | Quatro grupos de práticas: PO (preparar a organização), PS (proteger o software), PW (produzir bem) e RV (responder a vulnerabilidades). O rascunho 1.2 adiciona PO.6 (melhoria contínua) e PS.4 (atualizações confiáveis, com canário, rollback e proteção contra downgrade), segundo a [Cycode, fonte secundária](https://cycode.com/blog/nist-ssdf-1-2-changes-compliance-guide/). | Pouco: pede **evidência** de práticas. O SDD já gera muita evidência (gates). | Quase tudo é processo. O `gluon-spec` já cobre bem PW (testes, revisão) e parte de RV. |
| **SLSA** | **v1.2** (aprovada), com trilhas Build e **Source** ([spec](https://slsa.dev/spec/)) | Build L1: proveniência gerada automaticamente. L2: build em plataforma hospedada que assina a proveniência. L3: build isolado, com segredos de assinatura fora dos passos do usuário ([build track](https://slsa.dev/spec/v1.2/build-track-basics)). | **Sim**: a proveniência é verificável por máquina (`cosign verify-attestation`, `gh attestation verify`) | Escolher o nível e confiar na plataforma |
| **OpenSSF Scorecard** | **v5.6.0** (out/2026, [releases](https://github.com/ossf/scorecard/releases)) | São 20 checagens ([docs](https://github.com/ossf/scorecard/blob/main/docs/checks.md)), entre elas Branch-Protection, Code-Review, Dangerous-Workflow, Pinned-Dependencies, SAST, SBOM, Signed-Releases, Token-Permissions e Vulnerabilities | **Sim**, 100% automático (heurísticas). Mede a postura do **repositório**, não o código da feature. | Interpretar a nota |
| **OpenSSF OSPS Baseline** | **v2026.08.28** ([site](https://baseline.openssf.org/)) | Controles MUST por nível de maturidade para projetos (acesso, build e release, documentação, vulnerabilidades) | Grande parte | — |
| **CISA Secure by Design** | Princípios e o *Pledge*, com mais de 200 fabricantes ([página](https://www.cisa.gov/securebydesign), [pledge](https://www.cisa.gov/securebydesign/pledge)) | Sete metas: MFA, fim de senhas padrão, **reduzir classes inteiras de vulnerabilidade**, facilitar patches, política de divulgação (VDP), CVEs com CWE e CPE, e evidência de intrusão (logs) | Pouco | São metas de produto e organização |
| **SBOM** | **CycloneDX 1.7.2** ([releases](https://github.com/CycloneDX/specification/releases)) e **SPDX 3.0.1** ([releases](https://github.com/spdx/spdx-spec/releases)). Elementos mínimos: [CISA 2025](https://www.cisa.gov/resources-tools/resources/2025-minimum-elements-software-bill-materials-sbom), que acrescenta hash do componente, licença, ferramenta e contexto de geração. | Gerar o SBOM por artefato no build e guardá-lo junto ao release | **Sim**: gerar com Syft, Trivy ou cdxgen e validar o esquema | Decidir quem consome e como responder |

### 2.2 Mudanças relevantes do OWASP Top 10:2025

Fonte: [introdução oficial](https://top10.owasp.org/2025/0x00_2025-Introduction/).

- **A03 Software Supply Chain Failures** amplia "Vulnerable and Outdated Components" para incluir sistemas de build e distribuição. Tem poucas CWEs, mas a maior média de exploração e impacto, segundo a [Eclypsium](https://eclypsium.com/blog/owasp-top-10-2025-software-supply-chain-risk/).
- **A10 Mishandling of Exceptional Conditions** é nova: erros, falhar aberto (*fail open*) e lógica em condições anormais.
- **SSRF foi absorvido por A01 Broken Access Control.**
- **A02 Security Misconfiguration subiu de #5 para #2.**
- A base de dados cobre mais de 2,8 milhões de aplicações. Duas categorias vieram de pesquisa com a comunidade, porque testes automáticos ainda não as capturam.

**Implicação para o SDD:** A01, A06 e A10 são as menos detectáveis por ferramenta. Por isso precisam virar **comportamento na spec** (Mapa de Comportamentos e testes): caso de acesso negado, caso de erro que falha fechado e caso de abuso.

---

## 3. Controles concretos por ameaça

Legenda de responsabilidade: **[código]** é do time, testável na spec; **[config]** é configuração da aplicação ou framework, testável no G5 ou G6; **[infra]** é plataforma ou operação, fica em ADR e fora do gate de feature.

### 3.1 Injeção, XSS, CSRF, SSRF e controle de acesso

**Injeção (A05)**
- **[código]** Consultas parametrizadas ou ORM e APIs que não aceitam string concatenada. O Google relata ter "quase eliminado" XSS e SQL injection com APIs seguras por construção ([Safe Coding](https://research.google/pubs/safe-coding-rigorous-modular-reasoning-about-software-safety/)).
- **[máquina]** SAST pega boa parte dos casos.
- Teste: entrada maliciosa (`' OR 1=1--`) retorna erro ou resultado vazio.

**XSS**
- **[código]** Encoding de saída por contexto e templates com auto-escape.
- **[config]** CSP estrita, com nonce ou hash, `'strict-dynamic'`, `object-src 'none'` e `base-uri 'none'`. Primeiro em `Report-Only`, depois em enforcement ([web.dev strict CSP](https://web.dev/articles/strict-csp)).
- Código gerado por LLM é especialmente fraco aqui: só 12–13% foi seguro contra XSS no relatório da [Veracode 2025](https://www.veracode.com/press-release/ai-generated-code-poses-major-security-risks-in-nearly-half-of-all-development-tasks-veracode-research-reveals/). A cifra exata vem de fonte secundária; o número principal, de 45% das tarefas com falha, vem do release oficial.

**CSRF** ([OWASP CSRF CS](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html))
- Defesa primária: a proteção nativa do framework, um token sincronizador (stateful), um *signed double-submit* com HMAC (stateless) ou um header customizado em APIs.
- **Fetch Metadata** (`Sec-Fetch-Site`) pode ser defesa primária só se o público for de navegadores modernos, com fallback para Origin e Referer.
- `SameSite` é **defesa em profundidade**, nunca a única defesa.
- **Nunca** mudar estado via GET.
- Teste automatizado: um POST cross-site sem token deve retornar 403.

**SSRF** ([OWASP SSRF CS](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html))
- **[código]** Allowlist de destinos. Montar a URL no servidor, com esquema, porta e path fixos.
- **[código]** Resolver o DNS e validar **todos** os IPs antes de conectar, contra DNS rebinding.
- **[código]** Desligar o seguimento de redirects.
- **[código]** Como último recurso, bloquear RFC1918, link-local e `169.254.169.254`, normalizando IPv4-mapeado.
- **[infra]** Segmentação de rede e IMDSv2.
- Teste: buscar `http://169.254.169.254/` deve ser rejeitado.

**Controle de acesso quebrado: IDOR/BOLA, A01 e API1/3/5**
- **[código]** Checagem de dono do objeto em **toda** operação, negar por padrão e autorização também por propriedade (API3).
- **Matriz de autorização** versionada (papel × endpoint × resposta esperada), testada automaticamente "por ponto de vista" de cada papel ([OWASP Authorization Testing Automation](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Testing_Automation_Cheat_Sheet.html)).
- É o controle de **maior retorno** e quase nenhuma ferramenta genérica o detecta: só testes do time.

### 3.2 Cookies e sessão

Fontes: [OWASP Session Management CS](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) e [MDN Cookies](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies).

| Controle | Valor recomendado | Teste automatizável |
|---|---|---|
| Atributos | `Secure; HttpOnly; SameSite=Strict` (ou `Lax`), explícitos, **sem `Domain`**, `Path` estreito | Teste de integração inspeciona o `Set-Cookie` |
| Prefixo | `__Host-` (exige `Secure`, sem `Domain`, `Path=/`). Existem também `__Http-` e `__Host-Http-`, que exigem `HttpOnly` ([MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies)) | Idem |
| ID de sessão | Gerado por CSPRNG, com 64 bits ou mais de entropia (128 ou mais se for próprio). Preferir o do framework. | Revisão ou ADR |
| Rotação | Novo ID no login e em qualquer mudança de privilégio. O antigo é destruído. Rejeitar IDs não emitidos. | Teste: o ID antes do login difere do ID depois, e o antigo é rejeitado |
| Expiração | Timeout por inatividade e absoluto **no servidor**: 2–5 min em app de alto valor, 15–30 min em baixo risco, e 4–8 h absoluto em app de escritório | Teste com relógio controlado |
| Logout | Invalida no servidor todos os IDs da sessão lógica. `Clear-Site-Data` | Teste: reusar o cookie após o logout retorna 401 |
| Armazenamento | **Nunca** token ou sessão em `localStorage` ou `sessionStorage`. Usar cookie HttpOnly ou BFF. | SAST com regra customizada, ou revisão |
| Cache | `Cache-Control: no-store` em respostas com dado de sessão | Teste de integração |

Headers de segurança ([OWASP HTTP Headers CS](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html)):
- **Usar:**
  - CSP com `frame-ancestors`;
  - `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`;
  - `X-Content-Type-Options: nosniff`;
  - `Referrer-Policy: strict-origin-when-cross-origin`;
  - `Permissions-Policy` restritiva;
  - COOP, COEP e CORP conforme o caso.
- **Não usar:** `X-XSS-Protection` (ou defini-lo como `0`), `Expect-CT` e HPKP.
- Isso é **verificável por máquina** no G6, com um smoke de headers ou o ZAP baseline.

### 3.3 Vazamento de segredos e de PII

- **Prevenção em camadas:**
  1. Hook de pre-commit local com scanner de segredos.
  2. Varredura no CI, incluindo o histórico.
  3. Push protection da plataforma.
  4. **Resposta:** revogar e rotacionar. O incidente [tj-actions (CVE-2025-30066)](https://www.wiz.io/de-de/blog/github-action-tj-actions-changed-files-supply-chain-attack-cve-2025-30066) imprimiu segredos de CI em logs e exigiu rotação em massa. O [alerta da CISA sobre o worm Shai-Hulud](https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem) (set/2025) pediu revisão de dependências e **rotação de credenciais de desenvolvedor**.
- **Credenciais de publicação de curta duração:** OIDC e *trusted publishing* no lugar de tokens longos. Em out/2025 o npm iniciou o fim dos tokens clássicos e limitou tokens de escrita a 90 dias ([GitHub changelog](https://github.blog/changelog/2025-10-10-strengthening-npm-security-important-changes-to-authentication-and-token-management)).
- **PII:**
  - classificação dos dados;
  - mascaramento em log testado (já está no baseline);
  - o [OWASP Logging CS](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) lista o que nunca logar;
  - mensagens de erro sem detalhes internos (ligado à A10:2025).

### 3.4 DDoS e abuso: o que é do código e o que é da infra

Fontes: [OWASP API4:2023](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/) e [OWASP DoS CS](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html).

| Camada | Controle | Dono | Entra no gate? |
|---|---|---|---|
| Código | Limites de tamanho: corpo, strings, arrays e upload | Time | **Sim.** Teste: payload acima do limite retorna 413 ou 400 |
| Código | Paginação com máximo validado no servidor | Time | **Sim.** Teste: `limit=100000` é truncado ou rejeitado |
| Código | Timeouts em chamadas de saída (HTTP, DB, LLM) e *circuit breaker* | Time | **Sim**, via NFR e teste de integração |
| Código | Regex sem backtracking catastrófico (ReDoS): engine linear (RE2) ou timeout, e limite de entrada antes do match | Time | **Sim**, com SAST e teste |
| Código | Throttling por operação sensível: login, OTP, recuperação de senha, envio de e-mail (API4, API6) | Time | **Sim.** Teste: a N+1ª tentativa retorna 429 |
| Código | Validação barata antes da cara, trabalho pesado assíncrono | Time | Revisão (G4) |
| Código | Teto de gasto com terceiros (LLM, SMS) e alertas de billing (API4, LLM10) | Time e ops | ADR |
| Config | Rate limit global por IP ou chave no gateway ou reverse proxy | Plataforma | ADR, com smoke opcional no G6 |
| Infra | WAF, CDN, proteção L3/L4 e L7 volumétrica, scrubbing, timeouts de conexão contra *slowloris* | Infra | **Não.** Fica em ADR do pilar e é operado fora do SDD |
| Infra | Limites de container (CPU, memória, processos) | Plataforma | IaC scan (G5) |

Regra prática: **o código garante que nenhuma requisição isolada consiga custar caro**, por limites, timeouts, paginação e throttling de fluxos sensíveis. **A borda garante que muitas requisições baratas não derrubem o sistema** (WAF, CDN, DDoS). CAPTCHA ajuda contra abuso de funcionalidade, mas não contra DoS ([OWASP DoS CS](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html)).

### 3.5 Supply chain

- **Ataques reais recentes:**
  - **tj-actions/changed-files** (mar/2025): tags reescritas apontando para commit malicioso ([Wiz](https://www.wiz.io/de-de/blog/github-action-tj-actions-changed-files-supply-chain-attack-cve-2025-30066)).
  - **Shai-Hulud** (set/2025): worm em mais de 500 pacotes npm ([CISA](https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem)).
  - **trivy-action e setup-trivy** (19/03/2026): 76 de 77 tags reescritas e um binário malicioso v0.69.4 publicado. Só a tag protegida por *immutable releases* escapou ([Aqua](https://www.aquasec.com/blog/trivy-supply-chain-attack/)). **O próprio scanner de segurança foi o vetor.**
- **Controles:**
  - **Pinning por SHA completo** de actions e imagens base (digest). O GitHub permite **impor** isso por política desde ago/2025 ([changelog](https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions/)). Releases imutáveis estão em GA desde 28/10/2025 ([changelog](https://github.blog/changelog/2025-10-28-immutable-releases-are-now-generally-available/)).
  - **Lockfile** com integridade (hash). Instalação reprodutível (`--frozen-lockfile`, `npm ci`).
  - **Cooldown** para versões novas:
    - pnpm `minimumReleaseAge`, padrão de 24 h no pnpm 11 ([pnpm blog](https://pnpm.io/blog/2025/12/05/newsroom-npm-supply-chain-security));
    - npm `min-release-age`, desde o 11.10.0 ([Socket](https://socket.dev/blog/npm-introduces-minimumreleaseage-and-bulk-oidc-configuration), fonte secundária).
    - Isso mitiga worms que vivem poucas horas, mas tem custo: conflita com bots de update ([Classmethod](https://dev.classmethod.jp/en/articles/pnpm-11-minimum-release-age-dependabot-ci-failure/)).
  - **Pacote malicioso ou typosquatting:** SCA tradicional (base de CVE) **não pega** pacote malicioso novo. Há bases e ferramentas específicas: avisos `MAL-` no OSV ([osv.dev](https://osv.dev/)), [GuardDog](https://github.com/DataDog/guarddog) e o [OpenSSF package-analysis](https://github.com/ossf/package-analysis). Na revisão, toda dependência nova deve ser justificada; o `verify` do SDD já alerta sobre mudança em manifesto.
  - **Permissões mínimas do token de CI** (`permissions:` read-only no topo) e nada de `pull_request_target` com checkout de código não confiável. Scorecard (Token-Permissions, Dangerous-Workflow) e [zizmor](https://docs.zizmor.sh/) detectam isso.
  - **Assinatura e proveniência:** [Sigstore cosign v3.1.4](https://github.com/sigstore/cosign/releases), [SLSA Build L2/L3](https://slsa.dev/spec/v1.2/build-track-basics) e npm trusted publishing, que gera proveniência automaticamente. **Verificar** a assinatura antes do deploy (G6).
  - **SBOM** por artefato: CycloneDX ou SPDX.

### 3.6 IaC e containers

- **[máquina]** Varredura de IaC: Terraform, Kubernetes, Dockerfile, Helm, CloudFormation. Procura buckets públicos, portas abertas, container root, falta de limites e segredos em variáveis. Ferramentas: Checkov, Trivy (misconfig), Kubescape, Hadolint; detalhes na seção 4.
- **[máquina]** Varredura de imagem: CVEs de SO e de linguagem, **imagem base fixada por digest**, imagem mínima ou distroless, usuário não root.
- **[humano]** Desenho de rede e IAM: menor privilégio, segmentação e IMDSv2.

### 3.7 Código gerado por IA e agentes

- **Risco do código gerado:** 45% das tarefas geraram código vulnerável em mais de 100 modelos ([Veracode 2025](https://www.veracode.com/press-release/ai-generated-code-poses-major-security-risks-in-nearly-half-of-all-development-tasks-veracode-research-reveals/)). Conclusão: código de agente passa **pelos mesmos gates**, sem exceção, e os testes de abuso (escritos antes, no red) são a defesa mais forte. Isso casa com o TDD do SDD.
- **Prompt injection** não tem defesa confiável hoje. A recomendação prática mais citada é a **Agents Rule of Two** da Meta (31/10/2025): numa sessão, o agente deve ter **no máximo dois** de três itens ([Meta AI](https://ai.meta.com/blog/practical-ai-agent-security/)):
  - [A] processa entrada não confiável;
  - [B] acessa sistema sensível ou dado privado;
  - [C] muda estado ou se comunica externamente.

  Se precisar dos três, use sessão nova ou aprovação humana. Isso é derivado da *lethal trifecta* de Simon Willison ([post](https://simonwillison.net/2025/Nov/2/new-prompt-injection-papers/)).
- **Permissões de tools:**
  - allowlist explícita por agente;
  - credenciais de curta duração e escopo mínimo (ASI02, ASI03);
  - sandbox para execução de código (ASI05);
  - saída do LLM tratada como **entrada não confiável** (LLM05);
  - limites de custo e tokens (LLM10).
- **Relevância dupla para o `gluon-spec`:**
  - o **produto** pode usar LLM, e isso vira pilar ou seção condicional;
  - o **próprio processo** é multiagente: subagentes leem issues, PRs e páginas web, que são entrada não confiável, e têm acesso de escrita ao repositório e ao CI. A Rule of Two se aplica à orquestração do SDD. Veja o [Microsoft SDL para IA (fev/2026)](https://www.microsoft.com/en-us/security/blog/2026/02/03/microsoft-sdl-evolving-security-practices-for-an-ai-powered-world/), que inclui threat modeling para IA e identidade de agente.

---

## 4. Ferramentas de mercado (abertas ou gratuitas, agnósticas)

Versões conferidas em 16/11/2026 nas páginas de release oficiais. "Local/CI" indica se roda nos dois.

| Camada | Ferramenta | Versão | Licença | Cobre | Não cobre | Local/CI |
|---|---|---|---|---|---|---|
| SAST | [Semgrep CE](https://github.com/semgrep/semgrep/releases) | v1.185.0 | LGPL-2.1 (as regras do registry têm licença própria) | Mais de 30 linguagens, regras customizáveis em YAML, modo *diff-aware* ([docs](https://semgrep.dev/docs/semgrep-ci/findings-ci)) | A versão CE não faz análise *cross-file* profunda (*taint* interprocedural é da versão paga). Lógica de negócio e autorização ficam de fora. | Sim / Sim |
| SAST | [Opengrep](https://github.com/opengrep/opengrep/releases) | v2.0.0 | LGPL-2.1 | Fork comunitário do Semgrep, com regras compatíveis | Idem | Sim / Sim |
| SAST | [CodeQL](https://github.com/github/codeql-cli-binaries/releases) | CLI v2.27.4 | Queries MIT, mas a **CLI só é gratuita para código open source**. Código privado exige GitHub Advanced Security ([licença](https://github.com/github/codeql-cli-binaries/blob/main/LICENSE.md)). | Análise semântica e de fluxo de dados profunda em cerca de 10 linguagens | Gratuidade só para OSS. Mais lento. | Sim / Sim |
| SCA | [OSV-Scanner](https://github.com/google/osv-scanner) | v2.7.1 | Apache-2.0 | Mais de 19 tipos de lockfile, imagens de container, licenças, modo offline, análise de chamada (reduz FP) e remediação guiada (npm e Maven) | Pacote malicioso só quando já está catalogado (`MAL-`). Ecossistemas fora da lista. Envia nomes e versões ao osv.dev se não for offline. | Sim / Sim |
| SCA e SBOM | [Grype](https://github.com/anchore/grype/releases) e [Syft](https://github.com/anchore/syft/releases) | v0.121.3 / v1.57.1 | Apache-2.0 | Syft gera SBOM (CycloneDX ou SPDX) de imagens e diretórios. Grype casa o SBOM com CVEs. | IaC, segredos e SAST | Sim / Sim |
| SBOM | [cdxgen](https://github.com/CycloneDX/cdxgen/releases) e [Dependency-Track](https://github.com/DependencyTrack/dependency-track/releases) | v13.8.0 / 5.2.1 | Apache-2.0 | Gera CycloneDX. O Dependency-Track monitora SBOMs continuamente, no pós-deploy. | — | Sim / Sim (o DT é um servidor) |
| Multi (SCA, IaC, segredos, container, licença) | [Trivy](https://trivy.dev/latest/docs/) | v0.76.2 | Apache-2.0 | Imagem, filesystem, repositório, Kubernetes, SBOM. Scanners de vulnerabilidade, misconfiguração, segredo e licença. | SAST de código próprio e DAST. **Atenção:** a action foi comprometida em mar/2026; fixe por SHA ou digest ([Aqua](https://www.aquasec.com/blog/trivy-supply-chain-attack/)). | Sim / Sim |
| Segredos | [Gitleaks](https://github.com/gitleaks/gitleaks/releases) | v8.30.1 (mar/2026) | MIT | Regex e entropia em repositório, histórico e stdin. Hook de pre-commit. | Validação ativa do segredo. Ritmo de releases caiu: o autor original criou o Betterleaks. | Sim / Sim |
| Segredos | [Betterleaks](https://github.com/betterleaks/betterleaks/releases) | v1.10.1 | MIT | Sucessor *drop-in* do Gitleaks pelo mesmo autor, que lê `.gitleaks.toml` e faz validação configurável ([BleepingComputer](https://www.bleepingcomputer.com/news/security/betterleaks-a-new-open-source-secrets-scanner-to-replace-gitleaks/amp/)) | Projeto novo, de 2026 | Sim / Sim |
| Segredos | [TruffleHog](https://github.com/trufflesecurity/trufflehog/releases) | v3.99.9 | **AGPL-3.0** | Mais de 800 detectores, **verifica se o segredo está ativo**, varre repositório, S3, Docker e Slack | AGPL pode pesar em uso embarcado. Mais lento. | Sim / Sim |
| IaC | [Checkov](https://github.com/bridgecrewio/checkov/releases) | 3.4.5 | Apache-2.0 | Terraform, CloudFormation, K8s, Helm, Dockerfile, ARM/Bicep e workflows de CI. Políticas em Python ou YAML. | Runtime. Algumas integrações (SCA) pedem chave da plataforma paga. | Sim / Sim |
| IaC e K8s | [Kubescape](https://github.com/kubescape/kubescape/releases) e [Hadolint](https://github.com/hadolint/hadolint/releases) | v4.0.21 / v2.15.1 | Apache-2.0 / GPL-3.0 | Postura K8s (NSA, CIS) / lint de Dockerfile | — | Sim / Sim |
| Política | [Conftest/OPA](https://github.com/open-policy-agent/conftest/releases) | v0.71.1 | Apache-2.0 | Regras próprias (Rego) sobre qualquer YAML, JSON ou HCL | Exige escrever as regras | Sim / Sim |
| CI/CD | [zizmor](https://docs.zizmor.sh/) | v1.32.0 | MIT | GitHub Actions, Dependabot e pre-commit: injeção de template, `uses` sem pin, permissões excessivas | Outros CIs | Sim / Sim |
| Postura do repositório | [OpenSSF Scorecard](https://github.com/ossf/scorecard) | v5.6.0 | Apache-2.0 | As 20 checagens da seção 2.1 | Código da aplicação | Sim / Sim |
| Assinatura | [cosign](https://github.com/sigstore/cosign/releases) | v3.1.4 | Apache-2.0 | Assinar e verificar imagens e blobs, atestações (SLSA, SBOM), modo *keyless* com OIDC | — | Sim / Sim |
| DAST | [ZAP](https://github.com/zaproxy/zaproxy/releases) | v2.17.0 (dez/2025) | Apache-2.0 | O *baseline scan* é **passivo**, leva poucos minutos e é "ideal para CI/CD, até contra produção". Regras FAIL, WARN e IGNORE em arquivo; códigos de saída próprios para gate ([docs](https://www.zaproxy.org/docs/docker/baseline-scan/)). Também tem full scan ativo e API scan (OpenAPI). | Autorização e lógica de negócio. O full scan é lento e só deve rodar contra staging. | Sim / Sim |
| DAST por template | [Nuclei](https://github.com/projectdiscovery/nuclei/releases) | v3.11.1 | MIT | Milhares de templates YAML (CVEs conhecidos, misconfigurações, exposições) e templates próprios | Lógica da aplicação | Sim / Sim |
| Fuzzing de API | [Schemathesis](https://github.com/schemathesis/schemathesis/releases) | v4.33.4 | MIT | Gera casos a partir de OpenAPI ou GraphQL: erros 500, violações de esquema, alguns problemas de segurança | Autorização entre usuários (só com configuração) | Sim / Sim |
| Fuzzing de código | [OSS-Fuzz](https://github.com/google/oss-fuzz) e [ClusterFuzzLite](https://google.github.io/clusterfuzzlite/), fuzzers nativos (Go `testing.F`, cargo-fuzz, Jazzer, Atheris) e *property-based testing* | — | Apache-2.0 | Parsers e decodificadores, crash e memória. O Scorecard já conta PBT como fuzzing ([checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md)). | Só faz sentido onde há parsing de entrada complexa | Sim / Sim |
| Pacote malicioso | [GuardDog](https://github.com/DataDog/guarddog) | v3.2.0 | Apache-2.0 | Heurísticas de pacote malicioso (npm, PyPI, Go, GitHub Actions) | Falsos positivos. Não substitui o cooldown. | Sim / Sim |

**Leitura agnóstica:** a skill **não deve citar nenhuma dessas ferramentas** em regra. Deve exigir que o projeto decida **uma por camada** (ou `N/A — motivo`) no ADR do pilar, como já faz com a tabela "Ferramenta por nível" do pilar `testes`. A tabela acima serve de material de pesquisa para quem preenche o ADR.

---

## 5. Como as empresas de ponta encaixam segurança no ciclo

1. **Threat modeling leve e contínuo, no design**
   - As quatro perguntas do [Threat Modeling Manifesto](https://www.threatmodelingmanifesto.org/), reproduzidas pelo [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html):
     1. O que estamos construindo?
     2. O que pode dar errado?
     3. O que vamos fazer a respeito?
     4. Fizemos um bom trabalho?
   - STRIDE (Spoofing, Tampering, Repudiation, Information disclosure, DoS, Elevation of privilege) é o roteiro mais comum para a segunda pergunta.
   - Cada ameaça recebe uma resposta (mitigar, eliminar, transferir ou aceitar). As mitigações viram **requisitos de segurança**, e o risco aceito é justificado por escrito.
2. **Triagem de risco por feature antes de envolver especialistas**
   - O [goSDL da Slack](https://slack.engineering/moving-fast-and-securing-things/) faz perguntas iniciais, calcula um nível de risco e gera checklist por componente. Só o risco alto aciona o time de segurança.
   - O repositório foi arquivado em nov/2025, mas o padrão continua válido.
   - É exatamente o modelo que cabe no G0: gatilhos que exigem a seção de ameaças.
3. **Casos de abuso como critérios de aceitação e testes automatizados**
   - O [OWASP Abuse Case CS](https://cheatsheetseries.owasp.org/cheatsheets/Abuse_Case_Cheat_Sheet.html) propõe:
     - ID único por caso de abuso;
     - inclusão nas user stories como critério de aceitação;
     - rastreabilidade no código;
     - testes automatizados que garantem que a contramedida "continua lá";
     - lista entregue ao pentester.
   - O próprio cheat sheet admite que abuse cases "raramente são usados na prática", e o motivo é o custo de workshop. **O SDD reduz esse custo**: a spec já tem Mapa de Comportamentos e IDs de teste.
4. **Matriz de autorização testada automaticamente**, com um teste por papel ([OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Testing_Automation_Cheat_Sheet.html)).
5. **Paved road e APIs seguras por construção**
   - O [Google Safe Coding](https://research.google/pubs/safe-coding-rigorous-modular-reasoning-about-software-safety/) e a meta "eliminar classes de vulnerabilidade" do [CISA Pledge](https://www.cisa.gov/securebydesign/pledge) vão na mesma direção.
   - No SDD isso é ADR com `enforced_by`. Exemplo: um teste de arquitetura que proíbe SQL por concatenação ou `innerHTML`, aplicado no G3.
6. **Security champions:** um dev por time com papel de referência em segurança. Veja o [OWASP Security Champions Guide](https://owasp.org/www-project-security-champions-guide/), que não é prescritivo. No SDD, o champion pode ser o revisor exigido no G4 para specs com gatilho de segurança.
7. **Gates no CI sem travar o time**
   - O Google mantém ferramentas de análise só se a taxa de "falso positivo efetivo" (achado que ninguém corrige) ficar baixa. Ferramenta com FP alto é desligada até ser corrigida ([CACM 2018](https://cacm.acm.org/magazines/2018/4/226371-lessons-from-building-static-analysis-tools-at-google/pdf); o patamar de 10% vem de [resenha secundária](https://medium.com/sourcedtech/paper-review-lessons-from-building-static-analysis-tools-at-google-cc71a43bdee)).
   - **Bloquear só achados novos** em relação à branch base. Exemplos: o *diff-aware scan* do [Semgrep](https://semgrep.dev/docs/semgrep-ci/findings-ci) e o arquivo de regras FAIL, WARN e IGNORE do [ZAP](https://www.zaproxy.org/docs/docker/baseline-scan/). O passivo legado vira backlog (spec), não um bloqueio de toda PR.
   - **Limiar por severidade:** crítico e alto bloqueiam; médio e baixo só avisam.
   - **Supressão com dono, motivo e expiração**, nunca silenciosa.
   - Rodar o rápido local (pre-commit de segredos) e o caro no CI ou à noite (DAST full, fuzzing).
8. **SDL como prática viva:** o [Microsoft SDL](https://www.microsoft.com/en-us/security/blog/2026/02/03/microsoft-sdl-evolving-security-practices-for-an-ai-powered-world/) (fev/2026) se apresenta como "jeito de trabalhar, não checklist" e inclui threat modeling de IA, observabilidade e identidade de agentes.

---

## 6. Proposta para o gluon-spec

Princípios mantidos: a skill continua **agnóstica** (não nomeia ferramenta); as regras são **verificáveis**; a tecnologia é escolha do projeto em ADR; e o rigor é **proporcional ao perfil** (`minimo`, `padrao`, `rigoroso`) e ao **risco da spec** (gatilhos).

### 6.1 Prioridade 1: seção "Ameaças e Mitigações" na spec, com testes `SEC-NN`

**O quê:**
- **No template `full`:** nova seção, depois do Mapa de Comportamentos (6.2) ou dentro dos NFRs, com:
  - **Gatilhos de segurança** (checklist): a spec
    - cria ou muda uma entrada externa (endpoint, formulário, fila, arquivo, webhook);
    - toca autenticação, autorização ou sessão;
    - lê ou grava dado pessoal ou sensível;
    - faz requisição para URL ou host vindo de entrada (SSRF);
    - faz upload ou parsing de formato complexo;
    - adiciona dependência ou action de CI;
    - muda IaC, imagem ou pipeline;
    - usa LLM ou agente com tools;
    - expõe fluxo de negócio abusável (login, OTP, cupom, envio).
  - **Tabela de ameaças** (STRIDE como roteiro). Colunas: `ID | Ameaça (ativo, fronteira) | STRIDE | Resposta (mitigar, eliminar, aceitar) | Mitigação | Teste`. Risco aceito exige justificativa e aprovação no H1.
  - **Testes de abuso `SEC-NN`** no Plano de Testes, que entram no red (G1) como qualquer teste. Exemplos:
    - `SEC-01` usuário B lê recurso de A → 404/403;
    - `SEC-02` payload maior que o limite → 413;
    - `SEC-03` sexta tentativa de OTP → 429;
    - `SEC-04` cookie de sessão com `__Host-`, `HttpOnly`, `Secure` e `SameSite`;
    - `SEC-05` URL interna é rejeitada;
    - `SEC-06` sessão invalidada após o logout.
- **No template `lite`:** uma linha "Gatilhos de segurança: nenhum | lista". Se houver gatilho, ao menos um `SEC-NN`.
- **G0 (deterministic, `validate`):** gatilho marcado exige a tabela de ameaças preenchida e ao menos um `SEC-NN` por ameaça com resposta "mitigar". Sem gatilho, vale "Nenhum gatilho" explícito (como já acontece com `user_facing`). Cada linha do Mapa de Comportamentos com regra de acesso precisa de um caso de acesso negado (hoje isso está só no ADR).
- **G0 (judgment):** acrescentar ao self-check do Architect: "as quatro perguntas de threat modeling foram respondidas para cada gatilho".

**Por quê:** A01, A06 e A10 do Top 10:2025, BOLA e lógica de negócio não são detectados por ferramenta (seção 2). O SDD já tem o mecanismo ideal: comportamento, ID de teste, red e verificação no Relatório de Entrega. Custo baixo e retorno máximo.

### 6.2 Prioridade 1: `security_scan` dividido por camada, com política de bloqueio

Proposta para `sdd-config.yml`, mantendo `security_scan` como alias legado:

```yaml
security:
  # Cada comando é escolha do projeto (ADR do pilar). "" = não configurado.
  secrets: ""        # G2 local (pre-commit) e G5. Varre diff e histórico.
  sca: ""            # G5. Vulnerabilidades em dependências (lockfile).
  sast: ""           # G5. Análise estática do código.
  iac: ""            # G5. IaC, Dockerfile, manifests, workflows de CI.
  container: ""      # G5. Imagem gerada.
  sbom: ""           # G5/G6. Gera o SBOM do artefato (perfil rigoroso).
  dast: ""           # G6. Contra staging (baseline passivo; ativo no rigoroso).
  verify_artifact: "" # G6. Verifica assinatura e proveniência antes do deploy.
  policy:
    block_severity: high       # critical | high | medium
    new_findings_only: true    # bloqueia só o que a mudança introduz
    suppressions_file: ""      # supressões com motivo, dono e expiração (validate checa a expiração)
```

- O `gate SPEC-X G5 --run` roda as chaves configuradas e grava uma linha por camada.
- O `validate` e o `pillars` avisam quando uma camada **exigida pelo perfil** está vazia e sem `N/A — motivo`.
- `secrets` também roda no **G2**: é barato e evita que o segredo chegue ao histórico.

### 6.3 Prioridade 2: G4 com checklist de segurança e revisor qualificado

- Trocar o item genérico do G4 por um bloco "Segurança", com os itens derivados do Top 10:2025 e do API Top 10:
  1. autorização por objeto e por propriedade em todo acesso novo (A01, API1, API3);
  2. entradas validadas e saídas codificadas, sem SQL ou comando concatenado (A05);
  3. erros falham fechado e não vazam detalhes (A10);
  4. sessão e cookies conforme o ADR (A07);
  5. limites, timeouts e paginação em toda entrada nova (API4);
  6. nenhum segredo ou PII em código, log ou mensagem (A04, A09);
  7. dependência nova justificada, fixada e sem alerta (A03);
  8. saída de LLM tratada como não confiável e tools com escopo mínimo (LLM05, LLM06, ASI02);
  9. cada ameaça da spec tem mitigação implementada e teste `SEC-NN` verde.
- **Perfil `rigoroso`** (ou spec com gatilho de autenticação, dado sensível ou pagamento): o G4 exige um revisor marcado como **security champion**, registrado em `--by "<revisor> (security)"`.
- Achados de segurança `blocker` ou `major` impedem o PASS. Isso já vale hoje; o que muda é o checklist explícito.

### 6.4 Prioridade 2: G3 com regras de segurança executáveis

Regras de "paved road" viram ADR com `enforced_by` e teste de arquitetura ou regra SAST customizada. Exemplos:
- acesso a banco só pela camada de repositório parametrizada;
- proibido `innerHTML`, `eval` ou equivalentes;
- HTTP de saída só pelo cliente que aplica allowlist e timeout (SSRF, DoS);
- configuração de cookie e headers centralizada num middleware único.

Assim, "eliminar classes de vulnerabilidade" ([CISA](https://www.cisa.gov/securebydesign/pledge), [Google](https://research.google/pubs/safe-coding-rigorous-modular-reasoning-about-software-safety/)) vira teste que roda em toda spec.

### 6.5 Prioridade 2: G6 com checagem de segurança no ambiente

- **Staging:**
  - `dast` com baseline passivo e regras FAIL/WARN versionadas;
  - smoke de segurança: headers presentes, cookie com atributos certos, HTTP redireciona para HTTPS, endpoint administrativo nega anônimo.
- **Antes de produção (perfil `rigoroso`):** `verify_artifact`, ou seja, o artefato implantado tem assinatura e proveniência válidas e corresponde ao commit do G5.
- **Evidência:** relatório do DAST e resultado da verificação.

### 6.6 Prioridade 3: pilares e ADRs baseline

| Mudança | Perfil | Regras verificáveis propostas para o baseline |
|---|---|---|
| **Novo pilar `seguranca-aplicacao`** (Segurança de aplicação web/API) | padrão | Nível ASVS alvo declarado (L1, L2 ou L3, por perfil). Encoding de saída e consulta parametrizada por padrão (APIs seguras por construção, com teste de arquitetura). CSP estrita (report-only, depois enforcement). Headers de segurança (lista OWASP). Proteção CSRF do framework. Allowlist para requisições de saída. Teste de headers no G6. |
| **Ampliar `seguranca-acesso`** | padrão | Cookie de sessão com `__Host-`, `Secure`, `HttpOnly`, `SameSite`. Regeneração do ID no login e em mudança de privilégio. Timeouts de inatividade e absoluto no servidor. Logout invalida no servidor. Nada de token em `localStorage`. **Matriz de autorização versionada e testada por papel.** |
| **Novo pilar `protecao-abuso`** (Proteção contra abuso e DoS) | **padrão**. Hoje isso só aparece em `desempenho-escala`, que é do perfil rigoroso. | Limite de payload, de itens e de upload em toda entrada. Paginação com máximo. Timeout em toda chamada de saída. Regex sem backtracking catastrófico. Throttling em fluxos sensíveis (login, OTP, recuperação de senha). Teto de gasto com terceiros. **A camada de borda (WAF, CDN, DDoS) é decidida aqui, mas operada fora do SDD.** |
| **Ampliar `dependencias`**, ou criar o pilar `integridade-build` (supply chain) | padrão (SBOM, assinatura e SLSA no rigoroso) | Actions e imagens fixadas por SHA ou digest, com política que impõe. Token de CI com permissão mínima. Cooldown para versões novas. Toda dependência nova justificada no PR. Credencial de publicação de curta duração (OIDC). SBOM por artefato (rigoroso). Assinatura e proveniência verificadas no deploy, SLSA Build L2 ou L3 (rigoroso). Postura do repositório medida (Scorecard ou equivalente). |
| **Ampliar `segredos-dados`** | mínimo | Varredura de segredo **antes do commit** (local) e no histórico. Procedimento de vazamento: revogar e rotacionar com prazo. |
| **Novo pilar condicional `ia-agentes`** | qualquer perfil, **só se o produto usa LLM ou agentes** (análogo a `user_facing`) | Rule of Two por sessão de agente. Allowlist de tools por agente. Credencial com escopo e curta duração. Saída do LLM tratada como entrada não confiável. Sandbox para execução de código. Limites de tokens e custo. Log de ações do agente. Testes `SEC-NN` de prompt injection indireta nas fronteiras. |
| **Ampliar `fluxo-mudanca`** | mínimo | Branch protection já existe. Acrescentar: política de divulgação de vulnerabilidade (`SECURITY.md`) e revisão obrigatória de mudanças em workflows de CI. |

### 6.7 Prioridade 3: o próprio processo SDD (agentes do gluon-spec)

Fica na skill e não no produto:
- subagentes que leem conteúdo externo (issues, PRs, web) não têm, **na mesma sessão**, credencial de push ou deploy (Rule of Two);
- o Integrator, que faz merge e push, não processa conteúdo não confiável;
- `references/multi-agent.md` documenta as permissões mínimas por papel.

Isso protege o pipeline SDD contra *goal hijack* (ASI01) vindo de texto de issue ou PR.

### 6.8 Níveis por perfil (resumo)

| Item | `minimo` | `padrao` | `rigoroso` |
|---|---|---|---|
| Alvo ASVS | L1 | L2 | L3 |
| Gatilhos e seção Ameaças na spec | Lista de gatilhos e `SEC-NN` para acesso e segredos | Tabela STRIDE completa quando há gatilho | Idem, mais revisão de ameaças pelo champion no H1 |
| `security.secrets` (G2 e G5) | **obrigatório** | obrigatório | obrigatório |
| `security.sca` | obrigatório (bloqueia crítico) | obrigatório (bloqueia alto) | obrigatório (bloqueia alto, mais pacote malicioso) |
| `security.sast` | recomendado | **obrigatório** (novos achados) | obrigatório, mais regras próprias do projeto |
| `security.iac` / `container` | se houver IaC ou imagem | obrigatório se houver | obrigatório se houver |
| Matriz de autorização testada | — | obrigatória quando há papéis | obrigatória |
| G4 com checklist de segurança | sim | sim | sim, com revisor champion |
| G6 `dast` | — | baseline passivo em staging | baseline mais ativo ou API scan em staging |
| SBOM, assinatura, proveniência | — | pinning de CI e lockfile | SBOM, assinatura e SLSA Build L2 ou mais, verificados no G6 |
| Fuzzing | — | PBT em parsers críticos (recomendado) | fuzzing em parsers e decodificadores |
| Pentest externo, bug bounty | fora | fora (recomendado anual) | fora do gate, registrado em ADR com periodicidade |

### 6.9 O que fica fora do gate (infra e operação)

Fica registrado em ADR, mas não bloqueia spec de feature:
- WAF, CDN e mitigação DDoS volumétrica (L3/L4/L7);
- segmentação de rede;
- SIEM, detecção e resposta a incidentes;
- gestão de vulnerabilidades em runtime (monitoramento contínuo de SBOM);
- pentest periódico, bug bounty, VDP e operação de CVE;
- rotação operacional de chaves.

Quando um desses itens for criado ou mudado como **código** (IaC), ele passa pelo `security.iac` normalmente.

### 6.10 Ordem sugerida de entrega (specs)

Cada uma é uma spec com H1:
1. **SPEC A:** seção "Ameaças e Mitigações", gatilhos, prefixo `SEC` e validação no G0 (templates, `validate`, `testing.md`).
2. **SPEC B:** bloco `security:` em `sdd-config.yml`, gravação por camada no G5, `secrets` no G2, política de bloqueio e supressões com expiração. Mantém compatibilidade com `security_scan`.
3. **SPEC C:** checklist de segurança no G4 e revisor champion por perfil.
4. **SPEC D:** novos baselines (`seguranca-aplicacao`, `protecao-abuso`, `ia-agentes` condicional), ampliação de `seguranca-acesso`, `dependencias` e `segredos-dados`, e catálogo de pilares 2026.12. Também sobe a versão do plugin, conforme o AGENTS.md.
5. **SPEC E:** checagens de segurança no G6 (`dast`, `verify_artifact`, smoke de segurança).
6. **SPEC F:** permissões mínimas por papel de agente no próprio SDD (`multi-agent.md`).

### 6.11 Questões em aberto para o humano decidir

1. **Gate novo ou distribuído?** A recomendação é **não criar um gate "GS"** e distribuir pelos gates G0, G2, G4, G5 e G6, para manter a ordem linear e a evidência no gate natural. A alternativa é um gate dedicado depois do G4, mais visível porém redundante. Qual prefere?
2. **Pilares novos ou ampliação?** Criar `seguranca-aplicacao`, `protecao-abuso`, `integridade-build` e `ia-agentes`, ou dobrar tudo em `seguranca-acesso` e `dependencias`? Pilares novos dão cobertura mais clara no `pillars`, mas aumentam a carga do perfil.
3. **`protecao-abuso` no perfil `padrao`?** Isso puxa limites e timeouts do `rigoroso` para o `padrao`. É defensável pelo API4:2023, mas aumenta a exigência para produtos comuns.
4. **Severidade que bloqueia por perfil:** a proposta é crítico no mínimo e alto no padrão e no rigoroso, sempre só achados novos. Confirmar.
5. **Supressão de achados:** onde fica o registro (arquivo próprio ou seção da spec)? Qual prazo máximo de expiração (30, 90 dias)? Quem aprova (Reviewer ou humano)?
6. **Security champion:** papel humano (H1 e H4) ou agente revisor com prompt de segurança? Agente revisor é mais barato, mas sujeito aos mesmos limites de LLM.
7. **Retrocompatibilidade:** manter `security_scan` como alias indefinidamente, ou fazer `validate` avisar e migrar?
8. **Brownfield:** como tratar o passivo de achados ao ligar SAST ou SCA pela primeira vez? A proposta é linha de base congelada, mais uma spec de redução do passivo, com bloqueio só do novo.
9. **Agentes do próprio SDD:** formalizar a Rule of Two nas permissões dos subagentes (afeta o `multi-agent.md` e talvez hooks) agora, ou só documentar como recomendação?
10. **ASVS como referência explícita:** a skill pode citar ASVS e OWASP por serem padrões abertos e neutros (já cita), mantendo a proibição de nomear ferramentas?

---

### Ressalvas da pesquisa

- **Fontes secundárias:**
  - nomes exatos de ASI01–ASI10;
  - detalhes do SSDF 1.2;
  - cooldown do npm;
  - percentual de XSS da Veracode;
  - o limiar de 10% do Google.
- **Status de documentos:**
  - o SSDF 1.2 ainda é **rascunho**;
  - o OWASP MCP Top 10 está em **beta**;
  - a página oficial do OWASP Top 10:2025 não mostra data de publicação final; a [The Register](https://www.theregister.com/2025/11/11/new_owasp_top_ten_broken/) noticiou a lista final em nov/2025.
- **Versões de ferramentas:** conferidas em 16/11/2026 e mudam rápido. O ADR do projeto deve registrar a versão e a data de verificação, como os baselines já pedem.
