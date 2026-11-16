/** O resultado mais recente de cada endereço, somando todos os lotes. */

import { Group, Stack, Text, Title } from "@mantine/core";
import { useState } from "react";

import { useResultados } from "../api/consultas";
import type { LinhaResultado } from "../api/tipos";
import { BotoesExportar } from "../componentes/BotoesExportar";
import { GavetaDetalhe } from "../componentes/DetalheEndereco";
import { contar } from "../componentes/filtros";
import { Indicadores } from "../componentes/Indicadores";
import { TabelaResultados } from "../componentes/TabelaResultados";
import { Carregando, Erro, Vazio } from "../ui/Estado";
import { formatarInteiro } from "../ui/formatar";

export function Resultados() {
  const consulta = useResultados();
  const [selecionada, setSelecionada] = useState<LinhaResultado | null>(null);

  return (
    <Stack gap="lg" className="bpr-pagina">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>Resultados</Title>
          <Text c="dimmed">
            Um endereço por linha, com a análise mais recente dele, de qualquer lote.
          </Text>
        </div>
        <BotoesExportar loteId={null} desabilitado={!consulta.data?.length} />
      </Group>
      {consulta.isPending ? <Carregando /> : consulta.isError ? <Erro erro={consulta.error} />
        : consulta.data.length === 0 ? (
          <Vazio titulo="Nenhum endereço analisado ainda." />
        ) : (
          <>
            <Indicadores itens={(() => {
              const n = contar(consulta.data);
              return [
                { rotulo: "Endereços", valor: formatarInteiro(n.total) },
                { rotulo: "Encontrados", valor: formatarInteiro(n.encontrados) },
                { rotulo: "Gravados no Excel", valor: formatarInteiro(n.gravados) },
                { rotulo: "Com recomendação", valor: formatarInteiro(n.comRecomendacao) },
                { rotulo: "Com problema", valor: formatarInteiro(n.comProblema) },
              ];
            })()} />
            <TabelaResultados linhas={consulta.data} aoSelecionar={setSelecionada} mostrarLote />
          </>
        )}
      <GavetaDetalhe loteId={selecionada?.lote_id ?? null} executionId={selecionada?.execution_id ?? null}
        enderecoid={selecionada?.enderecoid ?? null} aoFechar={() => setSelecionada(null)} />
    </Stack>
  );
}
