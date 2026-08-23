# Estratégia de verificação

## Conector

Comandos esperados:

```powershell
python scripts/verify_architecture.py
ruff check .
ruff format --check .
pytest
python -c "from api.index import app; print(app.title)"
```

Casos obrigatórios:

- credenciais corretas e snapshot completo;
- credenciais inválidas sem mensagem bruta;
- matrícula igual, divergente e esperada ausente;
- identidade vazia, timeout, `AuthError` e HTML incompatível;
- cliente fechado em sucesso e em toda falha;
- `SecretStr`, logs e resposta sem senha;
- revisão instalada igual ao SHA do pacote PucaVaz;
- repositório upstream igual à URL HTTPS canônica do PucaVaz;
- campos extras rejeitados em todos os níveis e limites de strings/listas aplicados;
- nenhuma pasta ou import de parser copiado.

## Aquário

Comandos esperados:

```powershell
npm run check-all
npm run test
npm run test:integration
npm run build
```

Casos obrigatórios:

- cache privado não atravessa logout ou troca de conta;
- beta, consentimento e reautenticação falham antes de chamar o conector;
- request com credenciais não é repetido automaticamente;
- mesma idempotency key é reservada antes da rede e não abre uma segunda sessão;
- lease vencido ou geração antiga não consegue instalar resultado tardio;
- matrícula nula é reivindicada na mesma transação do snapshot;
- matrícula de outra conta e curso sem alias bloqueiam sem vazar identidade;
- curso reconhecido e divergente não altera o perfil na primeira tentativa e devolve somente os dados necessários para a confirmação;
- confirmação exige proposta pendente, claim de reautenticação vinculado ao ID exato, novas credenciais, nova idempotency key e segunda consulta consistente;
- duas confirmações concorrentes com chaves diferentes não podem substituir o perfil duas vezes; exatamente uma transição `PENDING` para `CONSUMED` vence;
- proposta expirada, superada, concorrente ou ligada a identidade, matrícula, alias, consentimento ou destino alterado falha sem modificar perfil, snapshot ou dados manuais;
- retry idempotente da confirmação depois do lease não fica ocupado com uma data passada;
- idempotência e lease impedem duplicidade/conflito concorrente;
- falha mantém o último snapshot válido;
- tabelas manuais não mudam durante sync, desconexão ou exclusão;
- componentes manuais do curso anterior continuam visíveis na projeção depois de uma troca de curso;
- conflito de fontes mostra SIGAA e preserva manual;
- resposta privada usa `Cache-Control: private, no-store`;
- retenção remove metadados após 90 dias.
- `synchronizedAt` vem do commit no banco e não do relógio do navegador ou conector.

## Segurança e privacidade

- Buscar matrícula, senha de teste, cookies, HTML e PDF em logs capturados.
- Confirmar que PostHog não autocaptura nem grava a tela de credenciais e dados acadêmicos.
- Confirmar que os eventos do fluxo SIGAA usam apenas nomes e propriedades tipados. Inspecionar cada captura e rejeitar identidade, matrícula, curso, componentes, notas, contagens, mensagens de erro e credenciais.
- Testar usuário A contra todas as rotas de usuário B, inclusive por parâmetros extras.
- Testar payloads grandes, campos extras, versões desconhecidas e URL manipulada.
- Confirmar que segredo e URL do conector nunca chegam ao bundle do navegador.
- Confirmar rotação do bearer por ambiente e comparação constante no conector.
- Confirmar que preview não possui segredos reais e staging não contém snapshots de produção.
- Confirmar que o plano/região Vercel aceita os tetos configurados e observar um timeout real de 150 segundos em ambiente não produtivo.
- Forçar falha na resolução do deployment e na criação do alias. O workflow de staging deve falhar e não publicar um resumo de sucesso.

## Validação real da beta

1. Ativar `sigaa:beta` somente para a conta de teste.
2. Conferir a descrição completa do snapshot e conectar em staging isolado ou ambiente beta aprovado.
3. Comparar cada grupo de dados, incluindo notas, resultados e faltas, com a tela oficial do SIGAA.
4. Conferir estados vazio, desconectado e erro, fechar a espera sem cancelar a tentativa e repetir uma sincronização.
5. Forçar uma falha após existir snapshot e verificar preservação.
6. Fazer logout, entrar em outra conta e confirmar ausência de dados anteriores.
7. Desconectar e depois excluir os importados, validando as diferenças.
8. Inspecionar banco, logs e analytics em busca de dados proibidos.

Código verde sem esse smoke autenticado não conclui a beta.
