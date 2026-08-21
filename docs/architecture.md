# Opções de arquitetura avaliadas

## Opção escolhida

- Operação síncrona única.
- Pydantic no conector e Zod no Aquário, alinhados por fixtures douradas.
- Três conceitos persistidos: vínculo, último snapshot e tentativas seguras.
- JWT separado de reautenticação, finalidade SIGAA, duração de 15 minutos.
- Bearer server-only sobre HTTPS.
- SHA manual somente no `pyproject.toml`, revisão runtime derivada por PEP 610.
- Reserva de idempotência e lease com geração antes do I/O externo.

Ela é adequada à beta porque não cria armazenamento de credencial, fila, polling, replay store, geração cruzada ou tabela adicional de concessões.

O JWT pode ser reutilizado durante a janela de 15 minutos e o bearer pode ser repetido se vazar. A V1 aceita esses riscos com claims estritos, rate limit, memória apenas no navegador, segredo por ambiente, comparação constante e rotação documentada. Reautenticação de uso único e HMAC entram se o threat model ou a beta mostrarem necessidade concreta.

## Opção não escolhida agora

- JSON Schema como artefato canônico com geração Python/TypeScript.
- Reautenticação aleatória de uso único persistida por hash.
- HMAC por request com timestamp e replay store.
- Snapshot embutido na linha de conexão.

Partes reaproveitadas dessa opção:

- verificar digest/versão do contrato;
- gerar metadados de build a partir do pin, caso PEP 610 não esteja disponível no runtime Vercel;
- considerar concessão de uso único se a beta mostrar necessidade de revogação imediata;
- manter assinatura HMAC como endurecimento futuro se o conector tiver mais consumidores.

## Alternativas rejeitadas

- Copiar ou reescrever parsers. Isso cria dois donos do protocolo e perde a atribuição correta.
- Usar o serviço de sincronização SQLite upstream. Ele importaria uma política de persistência que não pertence ao conector.
- Misturar SIGAA nas tabelas manuais. As operações atuais de substituição poderiam apagar uma fonte pela outra.
- Criar job assíncrono na V1. Ele exige entregar ou persistir credenciais entre processos e complica sessão e cancelamento.
- Prometer cancelamento imediato. Abort do navegador e encerramento da função não fornecem essa garantia.
