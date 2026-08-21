# Conector SIGAA do Aquário

Este serviço conecta o backend do Aquário ao Sistema Integrado de Gestão de Atividades Acadêmicas (SIGAA) da Universidade Federal da Paraíba (UFPB). Ele autentica uma requisição privada, consulta os dados acadêmicos e devolve um snapshot normalizado sem armazenar credenciais, cookies, HTML ou arquivos PDF.

> [!IMPORTANT]
> Esta integração não é oficial e não possui vínculo, suporte ou endosso da UFPB ou do SIGAA.

## Estado do projeto

As fases 1 a 3 da versão V1 estão implementadas: contrato de dados, adaptador do cliente SIGAA e interface HTTP privada para Vercel. A integração com o backend e a interface do Aquário pertence às fases seguintes do [plano SIGAA V1](docs/implementation.md).

O serviço ainda exige um teste de inicialização válido no ambiente Vercel antes de qualquer liberação para usuários.

## Responsabilidades do conector

O conector possui uma fronteira pequena e deliberada:

- recebe credenciais SIGAA somente em `POST /v1/sync`
- usa o `SigaaClient` do projeto `sigaa-for-ai-agents`
- valida a matrícula antes de consultar os demais dados
- normaliza perfil, currículo, Coeficiente de Rendimento Acadêmico (CRA), notas e turmas
- encerra a sessão local após sucesso ou erro ordinário
- não possui banco de dados nem persiste respostas

O backend do Aquário continua responsável por reautenticação recente, autorização, limite de requisições, persistência atômica, retenção e exclusão dos dados.

## Estrutura do repositório

Cada diretório possui uma responsabilidade:

```text
api/                         Entrada Asynchronous Server Gateway Interface (ASGI)
docs/                        Arquitetura, implementação e verificação da V1
licenses/                    Licença da dependência upstream
scripts/                     Verificadores executáveis de arquitetura
src/aquario_sigaa_connector/ Contratos, segurança, provider e execução
tests/                       Testes unitários e testes HTTP sobre ASGI
```

## Dependência upstream

O projeto não copia parsers ou regras de navegação do SIGAA. Ele instala [`sigaa-for-ai-agents`](https://github.com/PucaVaz/sigaa-for-ai-agents), criado por Puca Vaz, diretamente do GitHub por um commit completo fixado em `pyproject.toml`.

O ambiente de execução lê a revisão instalada pelos metadados da [Python Enhancement Proposal (PEP) 610](https://peps.python.org/pep-0610/). Quando a Vercel remove esse metadado do bundle, o conector deriva a mesma revisão do `pyproject.toml` incluído na função. O verificador arquitetural rejeita divergências, URLs alternativas e imports diretos de `sigaa.parsers`.

Consulte [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) para os créditos e a licença preservada.

## Requisitos locais

Instale estes requisitos antes de executar o serviço:

- Python 3.12
- Git

Crie o ambiente virtual e instale o projeto com as dependências de desenvolvimento:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Defina `CONNECTOR_API_SECRET` no `.env` com pelo menos 32 caracteres aleatórios. Não envie esse arquivo ao Git.

Inicie a aplicação local:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.index:app --reload --env-file .env
```

O servidor inicia em `http://127.0.0.1:8000`.

## Configuração

O conector usa uma única variável de ambiente:

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `CONNECTOR_API_SECRET` | Sim | Segredo bearer compartilhado apenas com o backend do Aquário. Use pelo menos 32 caracteres aleatórios. |

Configure valores diferentes para Preview e Production. Nunca use prefixos públicos, como `NEXT_PUBLIC_`, e nunca envie esse segredo ao navegador.

## API HTTP

A API expõe somente duas rotas:

| Método | Rota | Autenticação | Finalidade |
| --- | --- | --- | --- |
| `GET` | `/health` | Não | Confirma que a função iniciou e informa a versão do contrato |
| `POST` | `/v1/sync` | Bearer | Executa uma sincronização completa e isolada |

Envie o bearer no cabeçalho `Authorization`:

```http
Authorization: Bearer connector_api_secret_here
```

O corpo de sincronização usa este formato:

```json
{
  "username": "20260000001",
  "password": "sigaa_password_here",
  "expected_matricula": "20260000001"
}
```

Use `null` em `expected_matricula` somente quando o perfil do Aquário ainda não possuir matrícula. Quando presente, o conector compara esse valor antes de buscar currículo, notas ou turmas.

Todas as respostas incluem `Cache-Control: no-store`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff` e um `X-Request-ID` gerado pelo servidor.

## Executar os gates

Execute os gates antes de criar um commit:

```powershell
.\.venv\Scripts\python.exe scripts\verify_architecture.py
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pytest.exe -q
```

O verificador confirma o pin upstream, a proveniência instalada ou incluída no bundle, a ausência de parsers locais, os contratos fechados, as rotas públicas e os limites da Vercel.

## Segurança e privacidade

Ao contribuir, preserve estas invariantes:

- não registre credenciais, matrícula, cookies, HTML ou conteúdo de PDF
- não devolva mensagens brutas de exceções upstream
- não aceite URL do conector ou identidade de usuário vindas do navegador
- não implemente retry automático de sincronização
- não copie parsers, seletores ou sessões HTTP do projeto upstream
- não altere o SHA upstream sem executar todos os gates

Relate uma vulnerabilidade diretamente aos mantenedores do Aquário. Não publique credenciais, respostas SIGAA ou dados acadêmicos em issues.

## Licenças

O código deste repositório usa a licença MIT disponível em [LICENSE](LICENSE). A licença da dependência upstream está preservada em [licenses/sigaa-for-ai-agents-MIT.txt](licenses/sigaa-for-ai-agents-MIT.txt).
