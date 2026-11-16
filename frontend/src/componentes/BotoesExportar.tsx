import { Button, Group } from "@mantine/core";

import { urlExportacao } from "../api/cliente";

/** Excel, CSV e JSON. São links: o navegador baixa o arquivo direto da API. */
export function BotoesExportar({ loteId, desabilitado }: { loteId: string | null; desabilitado?: boolean }) {
  const formatos = [
    { formato: "xlsx", rotulo: "Excel", icone: "bi-file-earmark-excel" },
    { formato: "csv", rotulo: "CSV", icone: "bi-filetype-csv" },
    { formato: "json", rotulo: "JSON", icone: "bi-filetype-json" },
  ];
  return (
    <Group gap="xs">
      {formatos.map(({ formato, rotulo, icone }) => (
        <Button
          key={formato}
          component="a"
          href={urlExportacao(loteId, formato)}
          download
          variant={formato === "xlsx" ? "filled" : "default"}
          size="xs"
          leftSection={<i className={`bi ${icone}`} />}
          disabled={desabilitado}
        >
          {rotulo}
        </Button>
      ))}
    </Group>
  );
}
