/** A tabela de resultados: um endereço por linha, com filtros, ordenação e
 * o mapa de status das ações. Usada no lote e em Resultados. */

import {
  Badge,
  Chip,
  Group,
  Pagination,
  Paper,
  Select,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useMemo, useState } from "react";

import type { LinhaResultado } from "../api/tipos";
import { formatarDuracao, formatarNumero } from "../ui/formatar";
import { LOCALIZACAO, PERSISTENCIA, seloDaAcao } from "../ui/selos";
import { SeloLocalizacao, SeloPersistencia, SimNao } from "../ui/Status";
import { Vazio } from "../ui/Estado";
import {
  FILTROS_VAZIOS,
  filtrarLinhas,
  ordenarLinhas,
  temProblema,
  type Coluna,
  type Filtros,
  type Ordem,
} from "./filtros";

const POR_PAGINA = 50;

/** As cores do Mantine pelo nome, para o mapa de ações. */
const COR_DO_SELO: Record<string, string> = {
  teal: "var(--mantine-color-teal-6)",
  orange: "var(--mantine-color-orange-6)",
  indigo: "var(--mantine-color-indigo-4)",
  gray: "var(--mantine-color-gray-4)",
  red: "var(--mantine-color-red-6)",
};

function MapaAcoes({ status }: { status: LinhaResultado["status_acoes"] }) {
  const itens = Object.entries(status);
  if (itens.length === 0) return <span className="bpr-apagado">–</span>;
  return (
    <div className="bpr-mapa-acoes" aria-label="Status das ações">
      {itens.map(([rotulo, valor]) => {
        const selo = seloDaAcao(valor);
        return (
          <Tooltip key={rotulo} label={`${rotulo}: ${selo.rotulo}`}>
            <span style={{ background: COR_DO_SELO[selo.cor] }} />
          </Tooltip>
        );
      })}
    </div>
  );
}

function Cabecalho({ coluna, rotulo, ordem, aoOrdenar, direita }: {
  coluna: Coluna;
  rotulo: string;
  ordem: Ordem;
  aoOrdenar: (coluna: Coluna) => void;
  direita?: boolean;
}) {
  const ativa = ordem.coluna === coluna;
  const seta = ativa ? (ordem.crescente ? "bi-caret-up-fill" : "bi-caret-down-fill") : "bi-chevron-expand";
  return (
    <Table.Th className="bpr-ordenavel" ta={direita ? "right" : undefined}
      onClick={() => aoOrdenar(coluna)} aria-sort={ativa ? (ordem.crescente ? "ascending" : "descending") : undefined}>
      {rotulo} <i className={`bi ${seta}`} style={{ opacity: ativa ? 1 : 0.35, fontSize: 11 }} />
    </Table.Th>
  );
}

export function TabelaResultados({ linhas, aoSelecionar, mostrarLote }: {
  linhas: LinhaResultado[];
  aoSelecionar: (linha: LinhaResultado) => void;
  mostrarLote?: boolean;
}) {
  const [filtros, setFiltros] = useState<Filtros>(FILTROS_VAZIOS);
  const [ordem, setOrdem] = useState<Ordem>({ coluna: "enderecoid", crescente: true });
  const [pagina, setPagina] = useState(1);

  const visiveis = useMemo(
    () => ordenarLinhas(filtrarLinhas(linhas, filtros), ordem),
    [linhas, filtros, ordem],
  );
  const paginas = Math.max(1, Math.ceil(visiveis.length / POR_PAGINA));
  const daPagina = visiveis.slice((Math.min(pagina, paginas) - 1) * POR_PAGINA,
    Math.min(pagina, paginas) * POR_PAGINA);

  function mudar(parcial: Partial<Filtros>) {
    setFiltros((atual) => ({ ...atual, ...parcial }));
    setPagina(1);
  }

  function ordenar(coluna: Coluna) {
    setOrdem((atual) => ({ coluna, crescente: atual.coluna === coluna ? !atual.crescente : true }));
  }

  const opcoesLocalizacao = [
    ...Object.entries(LOCALIZACAO).map(([value, s]) => ({ value, label: s.rotulo })),
    { value: "SEM_RESULTADO", label: "Sem resultado" },
  ];
  const opcoesPersistencia = [
    ...Object.entries(PERSISTENCIA).map(([value, s]) => ({ value, label: s.rotulo })),
    { value: "sem", label: "Sem gravação" },
  ];

  return (
    <Paper withBorder radius="lg" p="md">
      <Group gap="sm" mb="sm" align="flex-end" wrap="wrap">
        <TextInput
          label="Buscar"
          placeholder="Endereço, conclusão ou recomendação"
          leftSection={<i className="bi bi-search" />}
          value={filtros.busca}
          onChange={(e) => mudar({ busca: e.currentTarget.value })}
          w={280}
        />
        <Select label="Localização" placeholder="Todas" data={opcoesLocalizacao} clearable
          value={filtros.localizacao} onChange={(v) => mudar({ localizacao: v })} w={180} />
        <Select label="Gravação" placeholder="Todas" data={opcoesPersistencia} clearable
          value={filtros.persistencia} onChange={(v) => mudar({ persistencia: v })} w={160} />
        <Chip checked={filtros.soComProblema} onChange={(v) => mudar({ soComProblema: v })}
          color="red" variant="light">
          Com problema na auditoria
        </Chip>
        <Chip checked={filtros.soComRecomendacao}
          onChange={(v) => mudar({ soComRecomendacao: v })} variant="light">
          Com recomendação
        </Chip>
        <Text size="sm" c="dimmed" ml="auto" className="bpr-numero">
          {visiveis.length} de {linhas.length} endereços
        </Text>
      </Group>

      {visiveis.length === 0 ? (
        <Vazio titulo="Nenhum endereço com esses filtros.">Limpe a busca ou os filtros.</Vazio>
      ) : (
        <Table.ScrollContainer minWidth={1280}>
          <Table striped highlightOnHover verticalSpacing="xs" stickyHeader className="bpr-tabela">
            <Table.Thead>
              <Table.Tr>
                <Cabecalho coluna="enderecoid" rotulo="Endereço" ordem={ordem} aoOrdenar={ordenar} />
                <Cabecalho coluna="localizacao" rotulo="Localização" ordem={ordem} aoOrdenar={ordenar} />
                <Cabecalho coluna="persistencia" rotulo="Gravação" ordem={ordem} aoOrdenar={ordenar} />
                <Table.Th>Ações</Table.Th>
                <Cabecalho coluna="diferenca_aev" rotulo="Dif. AEV (m²)" ordem={ordem}
                  aoOrdenar={ordenar} direita />
                <Table.Th title="Adicionais redutíveis (2.2)">Adic. redutíveis</Table.Th>
                <Table.Th title="Ocupação de AEV acima da franquia (4.2)">Acima franquia</Table.Th>
                <Table.Th title="RF acima do limite por tecnologia (6.1)">RF acima limite</Table.Th>
                <Cabecalho coluna="recomendacoes" rotulo="Recomendações" ordem={ordem}
                  aoOrdenar={ordenar} direita />
                <Cabecalho coluna="problemas" rotulo="Auditoria" ordem={ordem} aoOrdenar={ordenar} />
                <Cabecalho coluna="duracao_s" rotulo="Duração" ordem={ordem} aoOrdenar={ordenar} direita />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {daPagina.map((linha) => (
                <Table.Tr key={linha.execution_id} className="bpr-linha-clicavel"
                  onClick={() => aoSelecionar(linha)}>
                  <Table.Td>
                    <Text fw={600} size="sm">{linha.enderecoid}</Text>
                    {mostrarLote && linha.lote_id && (
                      <Text size="xs" c="dimmed">{linha.lote_id}</Text>
                    )}
                  </Table.Td>
                  <Table.Td><SeloLocalizacao valor={linha.localizacao} /></Table.Td>
                  <Table.Td>
                    <SeloPersistencia valor={linha.persistencia} motivo={linha.persistencia_motivo} />
                  </Table.Td>
                  <Table.Td><MapaAcoes status={linha.status_acoes} /></Table.Td>
                  <Table.Td ta="right" className="bpr-numero">{formatarNumero(linha.diferenca_aev)}</Table.Td>
                  <Table.Td><SimNao valor={linha.adicionais_redutiveis} /></Table.Td>
                  <Table.Td><SimNao valor={linha.ocupacao_acima_franquia} /></Table.Td>
                  <Table.Td><SimNao valor={linha.rf_acima_limite} /></Table.Td>
                  <Table.Td ta="right" className="bpr-numero">
                    {linha.recomendacoes.length > 0 ? (
                      <Tooltip label={linha.recomendacoes.join(" · ")} multiline w={360}>
                        <Badge variant="light">{linha.recomendacoes.length}</Badge>
                      </Tooltip>
                    ) : "–"}
                  </Table.Td>
                  <Table.Td>
                    {temProblema(linha) ? (
                      <Tooltip multiline w={400} label={[
                        ...linha.erros_contrato, ...linha.alertas_coerencia,
                        ...(linha.erro_execucao ? [linha.erro_execucao] : []),
                      ].join(" · ")}>
                        <Badge color={linha.erros_contrato.length || linha.erro_execucao ? "red" : "orange"}
                          variant="light">
                          {linha.erros_contrato.length + linha.alertas_coerencia.length +
                            (linha.erro_execucao ? 1 : 0)} apontamento(s)
                        </Badge>
                      </Tooltip>
                    ) : <Text size="sm" c="dimmed">OK</Text>}
                  </Table.Td>
                  <Table.Td ta="right" className="bpr-numero">{formatarDuracao(linha.duracao_s)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      {paginas > 1 && (
        <Group justify="center" mt="md">
          <Pagination total={paginas} value={Math.min(pagina, paginas)} onChange={setPagina} />
        </Group>
      )}
    </Paper>
  );
}
