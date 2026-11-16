/** As 17 ações do Agente BPR, agrupadas por etapa. Nada marcado = todas.
 * A 5.2B (extração, com efeito colateral) só aparece liberada com a
 * extração autorizada. */

import { Badge, Button, Checkbox, Group, Paper, SimpleGrid, Stack, Text, Tooltip } from "@mantine/core";

import { useAcoes } from "../api/consultas";
import { Carregando, Erro } from "../ui/Estado";

const ETAPAS: Record<string, string> = {
  "1": "Consistência",
  "2": "Contrato",
  "3": "Situação do site",
  "4": "SCI e franquia",
  "5": "TSSR",
  "6": "RF e transmissão",
};

export function SeletorAcoes({ marcadas, aoMudar, permitirExtracao }: {
  marcadas: string[];
  aoMudar: (rotulos: string[]) => void;
  permitirExtracao: boolean;
}) {
  const consulta = useAcoes();
  if (consulta.isPending) return <Carregando texto="Carregando ações…" />;
  if (consulta.isError) return <Erro erro={consulta.error} />;

  const porEtapa = new Map<string, typeof consulta.data>();
  for (const acao of consulta.data) {
    const etapa = acao.rotulo.split(".")[0];
    porEtapa.set(etapa, [...(porEtapa.get(etapa) ?? []), acao]);
  }

  function alternar(rotulo: string, marcar: boolean) {
    aoMudar(marcar ? [...marcadas, rotulo] : marcadas.filter((r) => r !== rotulo));
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {marcadas.length === 0
            ? "Nenhuma marcada: o lote roda todas as ações."
            : `${marcadas.length} marcada(s). As dependências entram sozinhas.`}
        </Text>
        <Button variant="subtle" size="xs" onClick={() => aoMudar([])} disabled={marcadas.length === 0}>
          Limpar (todas)
        </Button>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
        {[...porEtapa.entries()].map(([etapa, acoes]) => (
          <Paper key={etapa} withBorder p="sm" radius="md">
            <Text className="bpr-rotulo" mb={6}>Etapa {etapa} · {ETAPAS[etapa] ?? ""}</Text>
            <Stack gap={6}>
              {acoes.map((acao) => {
                const bloqueada = acao.efeito_colateral && !permitirExtracao;
                const caixa = (
                  <Checkbox
                    key={acao.rotulo}
                    size="sm"
                    disabled={bloqueada}
                    checked={marcadas.includes(acao.rotulo)}
                    onChange={(e) => alternar(acao.rotulo, e.currentTarget.checked)}
                    label={
                      <Group gap={6} wrap="nowrap">
                        <Text size="sm"><b>{acao.rotulo}</b> {acao.titulo}</Text>
                        {acao.efeito_colateral && <Badge size="xs" color="orange">efeito colateral</Badge>}
                      </Group>
                    }
                    description={acao.depende_de.length ? `Depende de ${acao.depende_de.join(", ")}` : undefined}
                  />
                );
                return bloqueada ? (
                  <Tooltip key={acao.rotulo} label="Autorize a extração de TSSR para escolher a 5.2B.">
                    <div>{caixa}</div>
                  </Tooltip>
                ) : caixa;
              })}
            </Stack>
          </Paper>
        ))}
      </SimpleGrid>
    </Stack>
  );
}
