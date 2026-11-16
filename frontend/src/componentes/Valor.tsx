/** Um valor qualquer de campos_resultado, legível: lista vira itens,
 * objeto vira JSON, booleano vira Sim/Não. */

import { List, Text } from "@mantine/core";

import { formatarNumero } from "../ui/formatar";

export function Valor({ valor }: { valor: unknown }) {
  if (valor === null || valor === undefined || valor === "") {
    return <span className="bpr-apagado">–</span>;
  }
  if (typeof valor === "boolean") return <span>{valor ? "Sim" : "Não"}</span>;
  if (typeof valor === "number") return <span className="bpr-numero">{formatarNumero(valor)}</span>;
  if (Array.isArray(valor)) {
    if (valor.length === 0) return <span className="bpr-apagado">nenhum</span>;
    if (valor.every((v) => typeof v !== "object" || v === null)) {
      return (
        <List size="sm" spacing={2}>
          {valor.map((v, i) => <List.Item key={i}>{String(v)}</List.Item>)}
        </List>
      );
    }
  }
  if (typeof valor === "object") {
    return <pre className="bpr-json">{JSON.stringify(valor, null, 2)}</pre>;
  }
  return <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{String(valor)}</Text>;
}
