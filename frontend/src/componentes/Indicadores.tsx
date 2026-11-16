import { Paper, SimpleGrid, Text } from "@mantine/core";

export type Indicador = { rotulo: string; valor: string | number; nota?: string };

/** A fileira de números no topo da tela: o número lidera. */
export function Indicadores({ itens }: { itens: Indicador[] }) {
  return (
    <SimpleGrid cols={{ base: 2, sm: 3, lg: itens.length }} spacing="sm">
      {itens.map((item) => (
        <Paper key={item.rotulo} withBorder p="md" radius="lg">
          <div className="bpr-rotulo">{item.rotulo}</div>
          <div className="bpr-indicador">{item.valor}</div>
          {item.nota && <Text size="xs" c="dimmed">{item.nota}</Text>}
        </Paper>
      ))}
    </SimpleGrid>
  );
}
