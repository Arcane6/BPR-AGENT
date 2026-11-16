/** Os três estados de um painel além do dado: carregando, vazio (dizendo
 * o que fazer) e erro (com a mensagem da API). */

import { Alert, Center, Loader, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

export function Carregando({ texto = "Carregando…" }: { texto?: string }) {
  return (
    <Center py="xl">
      <Stack align="center" gap="xs">
        <Loader size="sm" />
        <Text size="sm" c="dimmed">{texto}</Text>
      </Stack>
    </Center>
  );
}

export function Vazio({ titulo, children }: { titulo: string; children?: ReactNode }) {
  return (
    <Center py="xl">
      <Stack align="center" gap={4} maw={420} ta="center">
        <i className="bi bi-inbox" style={{ fontSize: 28, opacity: 0.5 }} />
        <Text fw={600}>{titulo}</Text>
        {children && <Text size="sm" c="dimmed">{children}</Text>}
      </Stack>
    </Center>
  );
}

export function Erro({ erro }: { erro: unknown }) {
  const mensagem = erro instanceof Error ? erro.message : String(erro);
  return (
    <Alert color="red" variant="light" icon={<i className="bi bi-exclamation-octagon" />}
      title="Não deu certo">
      {mensagem}
    </Alert>
  );
}
