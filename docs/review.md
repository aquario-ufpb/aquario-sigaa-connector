# Revisão independente do plano

Revisor: `gpt-5.6-luna`, esforço alto.

Veredito final: aprovado condicionalmente no nível de arquitetura e plano. Não há bloqueador de desenho remanescente para iniciar a implementação faseada. A beta continua bloqueada até todas as provas determinísticas, migração em banco descartável, validação de ambientes e smoke autenticado passarem.

Correções incorporadas após a primeira revisão:

- reserva de idempotência antes da rede e lease com geração revalidada no commit;
- contrato recursivamente estrito, limites de payload e `CurriculumV1` completo;
- metadados de tentativa construídos no Aquário e `synchronizedAt` vindo do banco;
- regra determinística e fail-closed para curso divergente;
- operações e testes distintos para desconectar e excluir;
- orçamento de 150, 165 e 180 segundos, condicionado ao plano/região Vercel;
- cliente sem retry, cache privado isolado e analytics suprimido;
- identidade upstream limitada ao repositório HTTPS canônico do PucaVaz;
- retenção, ambientes e beta autenticada mantidos como gates de release.

Riscos aceitos para a V1:

- JWT de reautenticação reutilizável por até 15 minutos, mitigado por claims estritos, memória transitória e rate limit;
- bearer interno repetível em caso de vazamento, mitigado por HTTPS, segredo por ambiente, comparação constante e rotação;
- hard kill pode impedir `finally`, então a interface não promete cancelamento, logout remoto ou limpeza imediata de memória.

## Decisão posterior sobre curso divergente

A regra original mantinha qualquer divergência de curso como falha fechada definitiva. O requisito de produto foi ampliado para permitir correção explícita do perfil quando o SIGAA retorna um curso reconhecido no catálogo.

A primeira tentativa continua sem alterar o perfil nem instalar o snapshot. Ela cria uma proposta temporária sem credenciais. A confirmação mostra antes e depois, exige nova reautenticação vinculada à proposta, novas credenciais SIGAA e uma segunda consulta. O commit substitui curso e centro e instala o snapshot somente se a proposta e toda a identidade acadêmica continuarem válidas. Curso desconhecido ou proposta obsoleta continua falhando fechado.
