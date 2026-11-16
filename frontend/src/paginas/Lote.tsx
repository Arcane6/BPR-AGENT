/** Um lote: progresso enquanto roda, indicadores, tabela e exportação. */

import {
  Alert,
  Anchor,
  Badge,
  Breadcrumbs,
  Button,
  Group,
  List,
  Paper,
  Progress,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { SITUACOES_VIVAS, useLote, usePararLote } from "../api/consultas";
import type { LinhaResultado } from "../api/tipos";
import { BotoesExportar } from "../componentes/BotoesExportar";
import { GavetaDetalhe } from "../componentes/DetalheEndereco";
import { EmAnalise } from "../componentes/EmAnalise";
import { contar } from "../componentes/filtros";
import { Indicadores } from "../componentes/Indicadores";
import { TabelaResultados } from "../componentes/TabelaResultados";
import { Carregando, Erro, Vazio } from "../ui/Estado";
import { dataDoLote, formatarInteiro } from "../ui/formatar";
import { SeloSituacao } from "../ui/Status";

export function Lote() {
  const { loteId = "" } = useParams();
  const consulta = useLote(loteId);
  const parar = usePararLote(loteId);
  const [selecionada, setSelecionada] = useState<LinhaResultado | null>(null);

  if (consulta.isPending) return <Carregando />;
  if (consulta.isError) return <div className="bpr-pagina"><Erro erro={consulta.error} /></div>;

  const lote = consulta.data;
  const viva = SITUACOES_VIVAS.includes(lote.situacao);
  const numeros = contar(lote.linhas);
  const { concluidos, total } = lote.progresso;
  const rodando = new Set(lote.em_execucao.map((e) => e.enderecoid.toLocaleLowerCase("pt-BR")));
  const naFila = lote.pendentes.filter((e) => !rodando.has(e.toLocaleLowerCase("pt-BR")));

  return (
    <Stack gap="lg" className="bpr-pagina">
      <Breadcrumbs>
        <Anchor component={Link} to="/lotes">Lotes</Anchor>
        <Text>{lote.lote_id}</Text>
      </Breadcrumbs>

      <Group justify="space-between" align="flex-start">
        <div>
          <Group gap="sm">
            <Title order={2}>Lote de {dataDoLote(lote.lote_id)}</Title>
            <SeloSituacao situacao={lote.situacao} />
          </Group>
          {lote.pedido && (
            <Text c="dimmed" size="sm">
              {lote.pedido.escopo.executar.length} ação(ões)
              {lote.pedido.escopo.permitir_extracao ? " · com extração de TSSR" : " · sem extração"}
              {lote.pedido.pulados_ja_gravados.length > 0 &&
                ` · ${lote.pedido.pulados_ja_gravados.length} pulado(s) por já estarem gravados`}
            </Text>
          )}
        </div>
        <Group gap="sm">
          {lote.situacao === "em_andamento" && (
            <Button color="orange" variant="light" onClick={() => parar.mutate()} loading={parar.isPending}
              leftSection={<i className="bi bi-stop-circle" />}>
              Parar depois do endereço atual
            </Button>
          )}
          <BotoesExportar loteId={lote.lote_id} desabilitado={lote.linhas.length === 0} />
        </Group>
      </Group>

      {viva && (
        <Paper withBorder p="md" radius="lg">
          <Group justify="space-between" mb={6}>
            <Text size="sm" fw={600}>
              {lote.situacao === "parando" ? "Parando: termina o endereço em execução." : "Analisando…"}
            </Text>
            <Text size="sm" className="bpr-numero">{concluidos} de {total}</Text>
          </Group>
          <Progress value={total ? (100 * concluidos) / total : 0} animated striped size="lg" />
          <EmAnalise itens={lote.em_execucao} />
          {naFila.length > 0 && (
            <Text size="xs" c="dimmed" mt={6}>
              Na fila: {naFila.slice(0, 8).join(", ")}
              {naFila.length > 8 ? ` e mais ${naFila.length - 8}` : ""}
            </Text>
          )}
        </Paper>
      )}

      {lote.erro && <Alert color="red" title="O lote falhou">{lote.erro}</Alert>}
      {lote.situacao === "interrompido" && (
        <Alert color="orange" title="Lote interrompido" icon={<i className="bi bi-exclamation-triangle" />}>
          O processo parou antes de terminar. Os endereços abaixo foram gravados; para os
          {" "}{lote.pendentes.length || "demais"} restantes, comece um novo lote com “Pular endereços
          já gravados” ligado.
        </Alert>
      )}
      {lote.situacao === "parado" && lote.pendentes.length > 0 && (
        <Alert color="gray" title="Parado a pedido">
          Ficaram sem análise: {lote.pendentes.join(", ")}.
        </Alert>
      )}

      <Indicadores itens={[
        { rotulo: "Analisados", valor: formatarInteiro(numeros.total), nota: `de ${total}` },
        { rotulo: "Encontrados", valor: formatarInteiro(numeros.encontrados) },
        { rotulo: "Gravados no Excel", valor: formatarInteiro(numeros.gravados) },
        { rotulo: "Com recomendação", valor: formatarInteiro(numeros.comRecomendacao) },
        { rotulo: "Com problema", valor: formatarInteiro(numeros.comProblema),
          nota: "na auditoria do orquestrador" },
      ]} />

      {lote.resumo && lote.resumo.recomendacoes_mais_frequentes.length > 0 && (
        <Paper withBorder p="md" radius="lg">
          <Text className="bpr-rotulo" mb={6}>Recomendações mais frequentes</Text>
          <List size="sm" spacing={4}>
            {lote.resumo.recomendacoes_mais_frequentes.map(([texto, vezes]) => (
              <List.Item key={texto}><Badge size="sm" variant="light" mr={6}>{vezes}×</Badge>{texto}</List.Item>
            ))}
          </List>
        </Paper>
      )}

      {lote.linhas.length === 0 ? (
        <Paper withBorder radius="lg">
          <Vazio titulo={viva ? "O primeiro endereço ainda está em análise." : "Nenhum endereço analisado."}>
            {viva ? "Cada endereço aparece aqui assim que termina." : undefined}
          </Vazio>
        </Paper>
      ) : (
        <TabelaResultados linhas={lote.linhas} aoSelecionar={setSelecionada} />
      )}

      <GavetaDetalhe loteId={lote.lote_id} executionId={selecionada?.execution_id ?? null}
        enderecoid={selecionada?.enderecoid ?? null} aoFechar={() => setSelecionada(null)} />
    </Stack>
  );
}