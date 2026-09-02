# Plano Aquário + SIGAA V1

## Resultado esperado

O dono do perfil conecta sua conta SIGAA, autoriza uma importação privada e vê o último retrato acadêmico válido no Aquário. O Aquário não persiste senha, cookies, HTML ou PDF. O conector não possui banco e não reimplementa o SIGAA.

## Donos das responsabilidades

| Componente | Responsabilidade |
| --- | --- |
| Aquário | Identidade, beta, consentimento, reautenticação, rate limit, persistência, conflito entre fontes e interface privada |
| `aquario-sigaa-connector` | Ponte HTTP, contrato estrito, sessão efêmera, normalização e erros seguros |
| `PucaVaz/sigaa-tools` | Login, navegação JSF, cookies, requisições SIGAA e parsers |

O conector instala o projeto do PucaVaz por SHA completo. Nenhum parser será copiado. README, `THIRD_PARTY_NOTICES.md`, licença upstream e interface devem creditar Puca Vaz e apontar para o repositório original.

## Contrato do produto

- A funcionalidade aparece apenas para o dono do perfil e para usuários com `sigaa:beta`.
- A primeira conexão exige consentimento versionado e reautenticação com a senha do Aquário.
- A prova de reautenticação dura 15 minutos e serve apenas para operações SIGAA.
- A chamada que contém senha SIGAA não usa o `apiClient` com retry automático.
- Se o perfil já tem matrícula, a matrícula provada pelo SIGAA deve ser igual.
- Se o perfil não tem matrícula, a matrícula provada é vinculada atomicamente ao instalar o primeiro snapshot.
- A comparação de curso usa NFKC, caixa e espaços normalizados, mais uma lista explícita e versionada de aliases aprovados. Não existe comparação fuzzy nem alteração silenciosa do curso público.
- Um curso reconhecido no catálogo, mas diferente do perfil, interrompe a sincronização e cria uma proposta temporária. A interface mostra curso e centro atuais, o valor bruto informado pelo SIGAA e o destino reconhecido. A substituição exige confirmação explícita, nova reautenticação vinculada à proposta e uma segunda consulta ao SIGAA antes do commit atômico.
- Curso ausente do catálogo, alias desconhecido, proposta expirada ou identidade acadêmica alterada falham fechado sem modificar perfil, snapshot ou dados manuais.
- O SIGAA vence conflitos apenas na leitura. Os registros manuais permanecem intactos.
- Somente o último snapshot válido é mantido. Tentativas guardam metadados seguros por 90 dias.
- Desconectar preserva o snapshot. Excluir dados importados remove conexão, snapshot e tentativas, sem tocar nos registros manuais.
- Fechar a tela significa parar de esperar. A tentativa pode continuar por até três minutos.

## Dados da V1

O snapshot inclui identidade acadêmica mínima, curso, período atual, CRA oficial, carga horária, progresso curricular, componentes concluídos, em curso e pendentes, turmas, horários, notas, resultados, faltas, data da sincronização, versão do contrato e revisão upstream.

O PDF de histórico usado pelo pacote para obter CRA permanece transitório em memória. Processos, notícias, tarefas, frequência detalhada, materiais, certificados, documentos e MCP ficam fora da V1.

## Fluxo

1. O Aquário corrige primeiro o isolamento de caches privados entre identidades.
2. O conector fica verde usando o pacote do PucaVaz fixado por SHA.
3. O Aquário cria modelos separados para vínculo, snapshot e tentativas.
4. O usuário reautentica, consente e envia credenciais SIGAA por uma chamada sem retry.
5. O Aquário cria uma tentativa e adquire um lease por usuário.
6. Fora da transação, o Aquário chama a URL fixa do conector com prazo menor que o teto da função.
7. O conector autentica, verifica a identidade primeiro e coleta os dados com um cliente exclusivo.
8. O Aquário valida a resposta e instala o snapshot em uma transação curta.
9. A leitura privada combina snapshot e dados manuais sem alterar nenhuma das fontes.
10. Se o curso reconhecido divergir, o Aquário guarda somente uma proposta temporária, limpa as credenciais e pede confirmação. Uma nova consulta valida a mesma matrícula e o mesmo curso antes de substituir curso e centro e instalar o snapshot em uma única transação.

## Decisão de arquitetura

A opção escolhida usa uma operação síncrona, contrato Pydantic no conector e Zod no Aquário, verificados por fixtures douradas. Todo modelo aninhado rejeita campos extras e limita strings, arrays e tamanho total. O Aquário usa um JWT separado, com finalidade SIGAA e validade de 15 minutos. O tráfego interno usa HTTPS e bearer server-only com comparação constante, rotação documentada e segredo diferente por ambiente. Idempotência, lease e rate limit ficam no banco do Aquário.

Antes da rede, o repositório reserva a chave de idempotência e emite uma geração de lease. O commit final só instala o resultado se a mesma geração ainda for dona do lease. Repetir a mesma chave retorna a tentativa existente. Uma tentativa antiga nunca pode sobrescrever uma sincronização mais nova.

O JWT de reautenticação é reutilizável dentro dos 15 minutos e não tem revogação imediata. Esse risco é aceito na beta porque o token é limitado por emissor, audiência, sujeito, finalidade e prazo, permanece apenas em memória, exige novas credenciais SIGAA para sincronizar e todas as operações recebem rate limit. Se a beta exigir revogação ou uso único, ele será trocado por uma concessão aleatória armazenada somente por hash.

Não entram agora geração de contrato entre linguagens, concessão de reautenticação persistida, fila, polling, armazenamento de sessão ou replay store. Esses mecanismos aumentariam a superfície operacional antes de existir uma necessidade comprovada.

## Condições para liberar a beta

- O conector passa lint, formatação, tipos, testes, verificador arquitetural e import da função Vercel.
- O Aquário passa `npm run check-all`, testes unitários e integração com banco.
- Migração é aplicada em banco descartável, não apenas materializada por `prisma db push`.
- Cache privado é isolado por usuário e limpo em logout/troca de identidade.
- A tela de credenciais não entra em autocapture, session replay ou logs.
- Preview não recebe credenciais reais. Staging não clona snapshots acadêmicos de produção.
- O teto de duração do plano Vercel é verificado antes do deploy.
- A validação final usa uma conta beta real e confere CRA, matrícula, disciplinas, turmas e notas contra o SIGAA.

## Princípios que alteraram o desenho

- `Model the Domain` separou vínculo, último snapshot e tentativa, sem contaminar tabelas manuais.
- `Boundary Discipline` deixou credenciais e sessão no transporte efêmero, parsers no projeto do PucaVaz e persistência no Aquário.
- `Separate Before Serializing Shared State` levou ao lease com geração e à reserva de idempotência antes da rede.
- `Build the Lever` exige um verificador arquitetural que detecta parser copiado, pin divergente, contrato permissivo e configuração de runtime incorreta.
- `Sequence Verifiable Units` colocou cache privado antes da UI e smoke real depois de todos os gates determinísticos.
- `Experience First` mudou a linguagem de cancelamento e sessão para promessas que a infraestrutura realmente cumpre.
