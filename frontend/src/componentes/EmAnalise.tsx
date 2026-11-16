/** Os endereços em análise agora: há quanto tempo, em que tentativa, quantas
 * vezes já foram ao modelo e qual foi a última ferramenta. É o que mostra se
 * um endereço está progredindo ou girando em falso. */

import { Badge, Table, Text, Tooltip } from "@mantine/core";

import type { EmExecucao } from "../api/tipos";
import { formatarDuracao, formatarInteiro } from "../ui/formatar";

// Um endereço normal leva poucos minutos; passou disto, vale olhar.
const DEMORANDO_S = 10 * 60;

export function EmAnalise({ itens }: { itens: EmExecucao[] }) {
  if (itens.length === 0) return null;
  return (
    <Table verticalSpacing={4} mt="sm" aria-label="Em análise agora">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Em análise agora</Table.Th>
          <Table.Th ta="right">Tempo</Table.Th>
          <Table.Th ta="right">Tentativa</Table.Th>
          <Table.Th ta="right">Chamadas ao modelo</Table.Th>
          <Table.Th>Última ferramenta</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {itens.map((item) => (
          <Table.Tr key={item.enderecoid}>
            <Table.Td><Text size="sm" fw={600}>{item.enderecoid}</Text></Table.Td>
            <Table.Td ta="right" className="bpr-numero">
              {item.segundos >= DEMORANDO_S ? (
                <Tooltip label="Mais de 10 minutos: se as chamadas ao modelo não sobem, ele pode estar preso.">
                  <Badge color="orange" variant="light">{formatarDuracao(item.segundos)}</Badge>
                </Tooltip>
              ) : formatarDuracao(item.segundos)}
            </Table.Td>
            <Table.Td ta="right" className="bpr-numero">
              {item.tentativa > 1 ? <Badge color="orange" variant="light">{item.tentativa}ª</Badge> : "1ª"}
            </Table.Td>
            <Table.Td ta="right" className="bpr-numero">{formatarInteiro(item.chamadas_modelo)}</Table.Td>
            <Table.Td>
              <Text size="xs" ff="monospace">{item.ultima_ferramenta ?? "pensando…"}</Text>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}