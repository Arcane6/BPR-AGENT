/** Os lotes em disco, do mais recente ao mais antigo. */

import { Badge, Button, Group, Paper, Progress, Stack, Table, Text, Title } from "@mantine/core";
import { Link, useNavigate } from "react-router-dom";

import { useLotes } from "../api/consultas";
import type { LoteNaLista } from "../api/tipos";
import { Carregando, Erro, Vazio } from "../ui/Estado";
import { dataDoLote } from "../ui/formatar";
import { SeloSituacao } from "../ui/Status";

const ORIGEM: Record<string, string> = {
  tela: "Tela",
  linha_de_comando_ou_chat: "Linha de comando ou chat",
};

function Contagens({ lote }: { lote: LoteNaLista }) {
  const encontrados = lote.localizacao?.ENCONTRADO ?? 0;
  const gravados = lote.persistencia?.registrado ?? 0;
  if (!lote.localizacao) return <Text size="sm" c="dimmed">–</Text>;
  return (
    <Group gap={4}>
      <Badge variant="light" color="teal">{encontrados} encontrado(s)</Badge>
      <Badge variant="light" color={gravados === lote.executados ? "teal" : "red"}>
        {gravados} gravado(s)
      </Badge>
      {Boolean(lote.com_problema_de_contrato) && (
        <Badge variant="light" color="red">{lote.com_problema_de_contrato} com problema</Badge>
      )}
    </Group>
  );
}

export function Lotes() {
  const consulta = useLotes();
  const navegar = useNavigate();
  return (
    <Stack gap="lg" className="bpr-pagina">
      <Group justify="space-between">
        <div>
          <Title order={2}>Lotes</Title>
          <Text c="dimmed">Todos os lotes da pasta de saída, venham da tela, do chat ou da linha de comando.</Text>
        </div>
        <Button component={Link} to="/" leftSection={<i className="bi bi-plus-lg" />}>Novo lote</Button>
      </Group>
      <Paper withBorder radius="lg" p="md">
        {consulta.isPending ? <Carregando /> : consulta.isError ? <Erro erro={consulta.error} />
          : consulta.data.length === 0 ? (
            <Vazio titulo="Nenhum lote ainda.">Comece um em “Novo lote” ou peça uma análise na conversa.</Vazio>
          ) : (
            <Table.ScrollContainer minWidth={800}>
              <Table highlightOnHover verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Lote</Table.Th>
                    <Table.Th>Situação</Table.Th>
                    <Table.Th>Progresso</Table.Th>
                    <Table.Th>Resultado</Table.Th>
                    <Table.Th>Origem</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {consulta.data.map((lote) => (
                    <Table.Tr key={lote.lote_id} className="bpr-linha-clicavel"
                      onClick={() => navegar(`/lotes/${lote.lote_id}`)}>
                      <Table.Td>
                        <Text fw={600} size="sm">{dataDoLote(lote.lote_id)}</Text>
                        <Text size="xs" c="dimmed" ff="monospace">{lote.lote_id}</Text>
                      </Table.Td>
                      <Table.Td><SeloSituacao situacao={lote.situacao} /></Table.Td>
                      <Table.Td w={200}>
                        <Text size="sm" className="bpr-numero">{lote.executados} de {lote.total}</Text>
                        <Progress value={lote.total ? (100 * lote.executados) / lote.total : 0} size="sm" />
                      </Table.Td>
                      <Table.Td><Contagens lote={lote} /></Table.Td>
                      <Table.Td><Text size="sm">{ORIGEM[lote.origem] ?? lote.origem}</Text></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
      </Paper>
    </Stack>
  );
}
