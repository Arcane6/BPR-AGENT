/** Medições e proteções: quanto os agentes consumiram no mês, dia a dia, e
 * o que as proteções barraram (GET /api/consumo, seguranca_bpr/consumo.py).
 * Sem texto de pergunta nem de resposta: só contagens. */

import { Badge, Group, Paper, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useState } from "react";

import { useConsumo } from "../api/consultas";
import { bloqueios, fatiaDoCache, n } from "../componentes/consumo";
import { Indicadores } from "../componentes/Indicadores";
import { Carregando, Erro, Vazio } from "../ui/Estado";
import { formatarInteiro, formatarNumero } from "../ui/formatar";

export function Consumo() {
  const [mes, setMes] = useState<string>("");
  const consulta = useConsumo(/^\d{4}-\d{2}$/.test(mes) ? mes : null);

  return (
    <Stack gap="lg" className="bpr-pagina">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Consumo e proteções</Title>
          <Text c="dimmed">
            Tokens do Agente BPR e do orquestrador, por dia, e o que as proteções barraram.
          </Text>
        </div>
        <TextInput type="month" label="Mês" value={mes} onChange={(e) => setMes(e.currentTarget.value)} />
      </Group>
      {consulta.isPending ? <Carregando /> : consulta.isError ? <Erro erro={consulta.error} /> : (() => {
        const dados = consulta.data;
        const t = dados.totais;
        const cache = fatiaDoCache(t);
        return (
          <>
            <Indicadores itens={[
              {
                rotulo: "Tokens do mês", valor: formatarInteiro(dados.tokens_do_mes),
                nota: dados.teto_tokens_mes
                  ? `Teto: ${formatarInteiro(dados.teto_tokens_mes)}${dados.teto_atingido ? " (atingido)" : ""}`
                  : "Sem teto",
              },
              { rotulo: "Endereços analisados", valor: formatarInteiro(n(t, "enderecos")) },
              { rotulo: "Turnos de conversa", valor: formatarInteiro(n(t, "turnos")) },
              { rotulo: "Entrada do cache", valor: cache === null ? "–" : `${formatarNumero(cache)}%` },
              { rotulo: "Bloqueios e recusas", valor: formatarInteiro(bloqueios(t)) },
            ]} />
            {dados.teto_atingido && (
              <Badge color="red" variant="light" size="lg">
                Teto do mês atingido: lotes e mensagens novos estão recusados.
              </Badge>
            )}
            {dados.por_dia.length === 0 ? <Vazio titulo="Nada consumido neste mês." /> : (
              <Paper withBorder radius="lg" p="sm" style={{ overflowX: "auto" }}>
                <Table striped highlightOnHover>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Dia</Table.Th>
                      <Table.Th ta="right">Endereços</Table.Th>
                      <Table.Th ta="right">Tokens dos lotes</Table.Th>
                      <Table.Th ta="right">Turnos</Table.Th>
                      <Table.Th ta="right">Tokens da conversa</Table.Th>
                      <Table.Th ta="right">Chamadas ao modelo</Table.Th>
                      <Table.Th ta="right">Bloqueios</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {dados.por_dia.map((d) => (
                      <Table.Tr key={d.dia}>
                        <Table.Td>{d.dia.split("-").reverse().join("/")}</Table.Td>
                        <Table.Td ta="right">{formatarInteiro(n(d, "enderecos"))}</Table.Td>
                        <Table.Td ta="right">{formatarInteiro(n(d, "lote_total"))}</Table.Td>
                        <Table.Td ta="right">{formatarInteiro(n(d, "turnos"))}</Table.Td>
                        <Table.Td ta="right">{formatarInteiro(n(d, "conversa_total"))}</Table.Td>
                        <Table.Td ta="right">
                          {formatarInteiro(n(d, "chamadas_lote") + n(d, "chamadas_conversa"))}
                        </Table.Td>
                        <Table.Td ta="right">{formatarInteiro(bloqueios(d))}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Paper>
            )}
            <div>
              <Title order={4} mb="xs">Proteções em vigor</Title>
              <Group gap="xs">
                {Object.entries(dados.protecoes).map(([nome, valor]) => (
                  <Badge key={nome} variant="outline" color="gray" tt="none">{`${nome}=${String(valor)}`}</Badge>
                ))}
                {dados.auditoria_linhas_perdidas > 0 && (
                  <Badge color="red" variant="light" tt="none">
                    {`${dados.auditoria_linhas_perdidas} linha(s) da auditoria perdida(s): confira a pasta`}
                  </Badge>
                )}
              </Group>
            </div>
          </>
        );
      })()}
    </Stack>
  );
}
