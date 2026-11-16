/** O detalhe de um endereço: o que o Agente BPR concluiu, ação por ação,
 * o que a auditoria do orquestrador apontou e as ferramentas chamadas. */

import {
  Accordion,
  Alert,
  Badge,
  Drawer,
  Group,
  List,
  Stack,
  Table,
  Tabs,
  Text,
  Timeline,
  Title,
} from "@mantine/core";

import { useDetalheEndereco } from "../api/consultas";
import type { DetalheEndereco as Detalhe } from "../api/tipos";
import { Carregando, Erro } from "../ui/Estado";
import { formatarDataHora, formatarDuracao, formatarInteiro } from "../ui/formatar";
import { SeloAcao, SeloLocalizacao, SeloPersistencia } from "../ui/Status";
import { Valor } from "./Valor";

function Lista({ titulo, itens, cor }: { titulo: string; itens: unknown; cor?: string }) {
  const lista = Array.isArray(itens) ? itens : [];
  return (
    <div>
      <Text className="bpr-rotulo" mb={4}>{titulo}</Text>
      {lista.length === 0 ? (
        <Text size="sm" c="dimmed">Nenhum.</Text>
      ) : (
        <List size="sm" spacing={4} c={cor}>
          {lista.map((item, i) => (
            <List.Item key={i}>{typeof item === "string" ? item : JSON.stringify(item)}</List.Item>
          ))}
        </List>
      )}
    </div>
  );
}

function Resumo({ detalhe }: { detalhe: Detalhe }) {
  const c = detalhe.consolidacao;
  const etapas = Object.entries(detalhe.conclusoes_etapas);
  return (
    <Stack gap="md">
      <div>
        <Text className="bpr-rotulo" mb={4}>Conclusão</Text>
        <Valor valor={c.CONCLUSAO_RESUMO} />
      </div>
      <Lista titulo="Recomendações preliminares" itens={c.RECOMENDACOES_PRELIMINARES} />
      <Lista titulo="Divergências" itens={c.DIVERGENCIAS} cor="orange" />
      <Lista titulo="Dados insuficientes" itens={c.DADOS_INSUFICIENTES} />
      {etapas.length > 0 && (
        <div>
          <Text className="bpr-rotulo" mb={4}>Conclusão por etapa</Text>
          <Table withRowBorders={false} verticalSpacing={4}>
            <Table.Tbody>
              {etapas.map(([campo, valor]) => (
                <Table.Tr key={campo}>
                  <Table.Td w={90}><Badge variant="outline">Etapa {campo.slice(1, -10)}</Badge></Table.Td>
                  <Table.Td><Valor valor={valor} /></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
      )}
      <Text size="xs" c="dimmed">
        Data de referência: {String(c.DATA_REFERENCIA ?? "–")}
      </Text>
    </Stack>
  );
}

function PorAcao({ detalhe }: { detalhe: Detalhe }) {
  const noEscopo = new Set(detalhe.escopo);
  return (
    <Accordion multiple variant="separated" radius="md">
      {detalhe.acoes.map((acao) => {
        const campos = Object.entries(acao.campos).filter(([k]) => !k.endsWith("_STATUS"));
        return (
          <Accordion.Item key={acao.abrev} value={acao.abrev}>
            <Accordion.Control>
              <Group justify="space-between" wrap="nowrap" pr="sm">
                <Text size="sm" fw={600} c={noEscopo.has(acao.abrev) ? undefined : "dimmed"}>
                  {acao.rotulo} · {acao.titulo}
                </Text>
                <SeloAcao status={acao.status} />
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              {campos.length === 0 ? (
                <Text size="sm" c="dimmed">
                  {noEscopo.has(acao.abrev) ? "Sem campos além do status." : "Fora do escopo deste lote."}
                </Text>
              ) : (
                <Table verticalSpacing={6} layout="fixed">
                  <Table.Tbody>
                    {campos.map(([campo, valor]) => (
                      <Table.Tr key={campo}>
                        <Table.Td w="42%"><Text size="xs" ff="monospace">{campo}</Text></Table.Td>
                        <Table.Td><Valor valor={valor} /></Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
}

const GRUPOS = [
  { severidade: "erro", titulo: "Contrato violado", cor: "red" },
  { severidade: "alerta", titulo: "Coerência duvidosa", cor: "orange" },
] as const;

function Auditoria({ detalhe }: { detalhe: Detalhe }) {
  return (
    <Stack gap="sm">
      {detalhe.erro && (
        <Alert color="red" title="Erro na execução" icon={<i className="bi bi-x-octagon" />}>
          {detalhe.erro}
        </Alert>
      )}
      {detalhe.problemas.length === 0 && !detalhe.erro ? (
        <Alert color="teal" variant="light" icon={<i className="bi bi-check2-circle" />}>
          A auditoria do orquestrador não apontou nada: o contrato está completo e as contas
          verificáveis batem.
        </Alert>
      ) : (
        GRUPOS.map(({ severidade, titulo, cor }) => {
          const doGrupo = detalhe.problemas.filter((p) => p.severidade === severidade);
          if (doGrupo.length === 0) return null;
          return (
            <Alert key={severidade} color={cor} variant="light" title={`${titulo} (${doGrupo.length})`}>
              <List size="sm" spacing={6}>
                {doGrupo.map((p, i) => (
                  <List.Item key={i}>
                    {p.mensagem}{" "}
                    <Text span size="xs" c="dimmed" ff="monospace">{p.codigo}</Text>
                  </List.Item>
                ))}
              </List>
            </Alert>
          );
        })
      )}
      <Table withRowBorders={false} verticalSpacing={4}>
        <Table.Tbody>
          <Table.Tr><Table.Td c="dimmed">Envelope</Table.Td>
            <Table.Td>{detalhe.origem_envelope === "persistencia"
              ? "reconstruído da gravação (a resposta veio sem JSON)" : "resposta final do agente"}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td c="dimmed">Tentativas</Table.Td><Table.Td>{detalhe.tentativas}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td c="dimmed">Regravações</Table.Td><Table.Td>{detalhe.regravacoes}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td c="dimmed">Início / fim</Table.Td>
            <Table.Td>{formatarDataHora(detalhe.inicio)} · {formatarDataHora(detalhe.fim)}
              {" "}({formatarDuracao(detalhe.duracao_s)})</Table.Td></Table.Tr>
          <Table.Tr><Table.Td c="dimmed">Tokens de entrada</Table.Td>
            <Table.Td className="bpr-numero">{formatarInteiro(detalhe.tokens.entrada)}
              {" "}({formatarInteiro(detalhe.tokens.entrada_em_cache)} em cache)</Table.Td></Table.Tr>
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function Chamadas({ detalhe }: { detalhe: Detalhe }) {
  if (detalhe.chamadas.length === 0) return <Text size="sm" c="dimmed">Nenhuma chamada registrada.</Text>;
  return (
    <Timeline bulletSize={18} lineWidth={2}>
      {detalhe.chamadas.map((chamada, i) => (
        <Timeline.Item key={i} title={<Text size="sm" fw={600} ff="monospace">{chamada.ferramenta}</Text>}>
          {chamada.status && <Badge size="xs" variant="light" mb={4}>{chamada.status}</Badge>}
          <pre className="bpr-json bpr-apagado">{JSON.stringify(chamada.args)}</pre>
        </Timeline.Item>
      ))}
    </Timeline>
  );
}

export function ConteudoDetalhe({ detalhe }: { detalhe: Detalhe }) {
  return (
    <Stack gap="md">
      <Group gap="xs">
        <SeloLocalizacao valor={detalhe.linha.localizacao} />
        <SeloPersistencia valor={detalhe.linha.persistencia} motivo={detalhe.linha.persistencia_motivo} />
        <Text size="xs" c="dimmed" ff="monospace">{detalhe.execution_id}</Text>
      </Group>
      <Tabs defaultValue="resumo" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="resumo">Resumo</Tabs.Tab>
          <Tabs.Tab value="acoes">Por ação</Tabs.Tab>
          <Tabs.Tab value="auditoria"
            rightSection={detalhe.problemas.length || detalhe.erro
              ? <Badge size="sm" color="red" variant="light">{detalhe.problemas.length + (detalhe.erro ? 1 : 0)}</Badge>
              : undefined}>
            Auditoria
          </Tabs.Tab>
          <Tabs.Tab value="chamadas">Chamadas</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="resumo" pt="md"><Resumo detalhe={detalhe} /></Tabs.Panel>
        <Tabs.Panel value="acoes" pt="md"><PorAcao detalhe={detalhe} /></Tabs.Panel>
        <Tabs.Panel value="auditoria" pt="md"><Auditoria detalhe={detalhe} /></Tabs.Panel>
        <Tabs.Panel value="chamadas" pt="md"><Chamadas detalhe={detalhe} /></Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

/** A gaveta lateral que abre ao clicar numa linha da tabela. */
export function GavetaDetalhe({ loteId, executionId, enderecoid, aoFechar }: {
  loteId: string | null;
  executionId: string | null;
  enderecoid: string | null;
  aoFechar: () => void;
}) {
  const consulta = useDetalheEndereco(loteId, executionId);
  return (
    <Drawer opened={Boolean(executionId)} onClose={aoFechar} position="right" size="xl"
      title={<Title order={3}>{enderecoid}</Title>}>
      {consulta.isPending ? <Carregando /> : consulta.isError ? <Erro erro={consulta.error} />
        : <ConteudoDetalhe detalhe={consulta.data} />}
    </Drawer>
  );
}
