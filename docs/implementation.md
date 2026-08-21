# Implementação faseada

Cada fase deve terminar verde antes da seguinte. Nenhuma fase publica, implanta ou altera o repositório do PucaVaz.

## Fase 1. Consolidar a fundação do conector

Arquivos principais:

- `pyproject.toml`
- `src/aquario_sigaa_connector/contracts.py`
- `scripts/verify_architecture.py`

Trabalho:

- Tornar `expected_matricula` anulável.
- Deixar o SHA fixado em `pyproject.toml` como única fonte manual e derivar a revisão por PEP 610 ou pelo pin incluído no bundle Vercel.
- Definir `CurriculumV1` por completo, incluindo CRA, cargas horárias, percentuais, contagens e componentes.
- Aplicar `extra="forbid"` recursivamente e limites explícitos para corpo, strings e listas.
- Fixar a identidade upstream ao repositório HTTPS canônico do PucaVaz e validar a mesma constante no Aquário.
- Criar um verificador que rejeite parser vendorizado, import direto de `sigaa.parsers`, SHA divergente, modelo aninhado permissivo e configuração Vercel incorreta.

Prova estática: `ruff check`, `ruff format --check` e verificador arquitetural.

Prova runtime: validar request/response com matrícula esperada presente, ausente e inválida.

## Fase 2. Fechar o adaptador do PucaVaz

Arquivos principais:

- `src/aquario_sigaa_connector/service.py`
- `src/aquario_sigaa_connector/errors.py`
- `tests/test_service.py`

Trabalho:

- Usar apenas `SigaaClient` para identidade, currículo/CRA, turmas e notas.
- Validar identidade não vazia antes de continuar.
- Mapear `AuthError`, credencial inválida, timeout, indisponibilidade e resposta não suportada para códigos seguros.
- Fechar o cliente em todos os caminhos normais e de erro.

Prova estática: nenhum dado secreto em `repr`, logger ou modelos de resposta.

Prova runtime: mocks do cliente comprovam ordem, fechamento e classificação de falhas.

## Fase 3. Fechar a borda HTTP e Vercel

Arquivos principais:

- `src/aquario_sigaa_connector/app.py`
- `api/index.py`
- `vercel.json`

Trabalho:

- Expor somente health mínimo e `POST /v1/sync` autenticado.
- Aplicar `Cache-Control: no-store`, IDs aleatórios de requisição e corpo máximo.
- Executar o provider síncrono em worker controlado, sem bloquear o event loop do ASGI.
- Configurar o conector com teto de função de 150 segundos, timeout do Aquário de 165 segundos e teto da rota Aquário de 180 segundos.
- Manter 30 segundos por request upstream e testar o comportamento quando o conector é encerrado pelo teto.
- Documentar que abortar o navegador não garante cancelamento do trabalho aceito.

Prova estática: importar a entrada ASGI e inspecionar rotas/configuração.

Prova runtime: teste HTTP real sobre ASGI com provider falso e sem rede SIGAA, incluindo timeout. O deploy fica bloqueado se o plano/região Vercel não suportar os tetos configurados.

## Fase 4. Corrigir isolamento privado no Aquário

Arquivos principais:

- `src/lib/client/query-keys.ts`
- `src/contexts/auth-context.tsx`
- testes do contexto e query keys

Trabalho:

- Incluir `usuarioId` em todas as query keys privadas `me`.
- Remover queries privadas no logout e na troca de identidade.
- Migrar chamadores existentes antes de remover as chaves antigas.

Prova estática: busca não encontra chave privada sem identidade.

Prova runtime: login A, cache, logout, login B e ausência total de dados de A.

## Fase 5. Modelar vínculo, snapshot e tentativas

Arquivos principais:

- `prisma/schema.prisma`
- nova migração SQL
- testes de migração/repositório

Trabalho:

- Adicionar `SigaaConnection`, `SigaaAcademicSnapshot` e `SigaaSyncRun`.
- Manter snapshot único por usuário, idempotência única, lease expirável com geração monotônica e códigos seguros.
- Não criar campos para senha, cookie, HTML, PDF, ViewState ou erro bruto.
- Criar índices para usuário, idempotência, lease e expiração de 90 dias.

Prova estática: revisão de schema, constraints e SQL de migração.

Prova runtime: aplicar e reverter a migração em banco descartável; provar unicidade e cascatas.

## Fase 6. Criar autorização específica SIGAA

Arquivos principais:

- `src/lib/server/services/sigaa/reauth.ts`
- `src/app/api/usuarios/me/sigaa/reauth/route.ts`
- testes de reautenticação

Trabalho:

- Reusar a comparação bcrypt da senha Aquário.
- Emitir JWT com segredo separado, `iss`, `aud`, `sub`, `purpose`, `jti`, `authTime` e expiração de 15 minutos.
- Exigir `sigaa:beta` no servidor.
- Aplicar rate limit distribuído às tentativas de reautenticação e operações SIGAA.
- Retornar `private, no-store` e nunca registrar corpo ou senha.

Prova estática: token comum e token SIGAA têm validadores e segredos separados.

Prova runtime: senha incorreta, usuário fora da beta, purpose errado, sujeito errado e expiração falham antes de I/O externo.

## Fase 7. Implementar o cliente e a sincronização

Arquivos principais:

- `src/lib/server/services/sigaa/sigaa-connector.ts`
- `src/lib/server/services/sigaa/synchronize-own-academic-data.ts`
- testes de integração da sincronização

Trabalho:

- Usar URL fixa server-only, bearer, contrato Zod estrito, request ID e timeout de 165 segundos.
- Expor no repositório operações atômicas `reserveAttempt`, `commitLatest` e `finishAttempt`.
- `reserveAttempt` deduplica `(usuarioId, idempotencyKey)`, aplica rate limit e devolve `runId`, `leaseToken` e `leaseGeneration` antes da chamada.
- `commitLatest` exige a mesma geração ainda válida, revalida identidade e instala matrícula, snapshot, conexão e conclusão da tentativa.
- `finishAttempt` encerra falhas com código seguro sem alterar o último snapshot.
- Fazer a chamada fora da transação.
- Construir metadados da tentativa no Aquário a partir de relógio, outcome mapeado, contagens validadas, versão e revisão. O conector não retorna `safeMetadata`.
- Gerar `synchronizedAt` pelo relógio do banco no commit e devolvê-lo na leitura privada.
- Comparar `student.course` com `Usuario.curso.nome` por normalização determinística e aliases versionados. Valor desconhecido ou divergente falha fechado.
- Preservar o snapshot anterior em qualquer falha.

Prova estática: credenciais não aparecem em tipos de repositório ou logging.

Prova runtime: mesma chave antes da rede, chaves concorrentes, lease vencido, resposta antiga tardia, matrícula nula, conflito de matrícula, curso divergente, resposta extra e timeout.

## Fase 8. Expor sincronização e leitura privadas

Arquivos principais:

- `src/app/api/usuarios/me/sigaa/sync/route.ts`
- `src/app/api/usuarios/me/academico/route.ts`

Trabalho:

- Não aceitar ID de usuário nem URL de conector do navegador.
- Usar um cliente dedicado com `retry: 0`; não chamar o `apiClient` atual com o corpo de credenciais.
- Exigir reautenticação recente para sincronizar.

Prova estática: todas as rotas derivam o dono de `withAuth` e retornam `private, no-store`.

Prova runtime: usuário A não consegue ler ou sincronizar dados de B; o GET privado retorna snapshot e `synchronizedAt` somente ao dono.

## Fase 9. Separar desconexão de exclusão

Arquivos principais:

- `src/app/api/usuarios/me/sigaa/disconnect/route.ts`
- `src/app/api/usuarios/me/sigaa/data/route.ts`
- testes do ciclo de vida SIGAA

Trabalho:

- `disconnect` muda o vínculo para desconectado e preserva snapshot e tentativas.
- `data` remove conexão, snapshot e tentativas importadas, preservando todos os dados manuais.
- Exigir reautenticação recente para as duas operações.

Prova estática: comandos e rotas diferentes, sem DELETE ambíguo.

Prova runtime: desconectar preserva leitura; excluir remove importados; dados manuais sobrevivem às duas operações.

## Fase 10. Criar a projeção acadêmica efetiva

Arquivos principais:

- `src/lib/server/services/sigaa/combine-academic-display.ts`
- `src/lib/shared/types/sigaa-academic.ts`
- testes da projeção

Trabalho:

- Combinar por código de disciplina sem mutar as fontes.
- SIGAA vence apenas a apresentação de conflitos.
- Preservar o valor manual e expor a origem.
- Manter componentes SIGAA sem correspondência no catálogo visíveis na página privada.

Prova estática: função pura e tipos discriminados por origem/estado.

Prova runtime: matriz de conflitos concluída, cursando, pendente, desconhecida e disciplina sem catálogo.

## Fase 11. Entregar a experiência privada

Arquivos principais:

- `src/app/usuarios/[slug]/usuario-profile-client.tsx`
- `src/components/pages/perfil/meus-dados-academicos-card.tsx`
- `src/app/me/academico/page.tsx`

Trabalho:

- Exibir o card apenas ao dono beta, inclusive antes da primeira sincronização.
- Criar consentimento, reautenticação, credenciais, progresso e resultado.
- Manter senha e prova recente somente no estado transitório e limpar em `finally`.
- Mostrar crédito e link para PucaVaz. Informar que senha não é persistida e que a sessão local fecha ao fim; não prometer logout remoto nem limpeza de RAM.
- Informar que “parar de esperar” não garante cancelamento e pode durar até três minutos.

Prova estática: campos sensíveis com autocomplete adequado e exclusão de captura/analytics.

Prova runtime: teste de navegador cobre dono, visitante, beta, consentimento, sucesso, erro, retry explícito e troca de conta.

## Fase 12. Retenção e ambientes

Arquivos principais:

- endpoint/job de limpeza de `SigaaSyncRun`
- configuração de cron
- workflows de preview/staging

Trabalho:

- Excluir diariamente tentativas com mais de 90 dias.
- Não fornecer segredo de conector nem acesso SIGAA real a previews.
- Impedir que o reset de staging copie snapshots acadêmicos de produção. Usar base isolada ou limpeza obrigatória antes do acesso.
- Validar os tetos de 150, 165 e 180 segundos no plano e região dos dois serviços. Hard kill pode impedir `finally`; a promessa pública continua limitada a não persistir nem reutilizar credenciais/sessão.

Prova estática: ambientes têm política explícita de segredos e dados.

Prova runtime: relógio controlado prova retenção; staging contém zero dados acadêmicos reais antes do smoke.

## Fase 13. Beta real e publicação controlada

Arquivos principais:

- `CHANGELOG.md` do Aquário
- `README.md` do conector
- checklist de beta

Trabalho:

- Liberar `sigaa:beta` primeiro para uma conta controlada.
- Comparar matrícula, curso, CRA, carga horária, disciplinas, turmas, notas e horários com o SIGAA.
- Confirmar logs, PostHog e banco sem credenciais ou conteúdo bruto.
- Publicar cada repositório em PR separado. Não alterar o upstream do PucaVaz.

Prova estática: diffs, licenças, créditos e changelogs revisados.

Prova runtime: smoke autenticado no ambiente beta e confirmação visual pelo usuário dono da conta.
