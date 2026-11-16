/** Selos de status (os dados estão em selos.ts). */

import { Badge, Loader, Tooltip } from "@mantine/core";

import type { SituacaoLote, StatusAcao } from "../api/tipos";
import { LOCALIZACAO, PERSISTENCIA, SITUACAO, seloDaAcao } from "./selos";

export function SeloAcao({ status }: { status: StatusAcao | null | undefined }) {
  const selo = seloDaAcao(status);
  return (
    <Badge color={selo.cor} variant="light" size="sm">
      {selo.rotulo}
    </Badge>
  );
}

export function SeloLocalizacao({ valor }: { valor: string | null }) {
  const selo = (valor && LOCALIZACAO[valor]) || { rotulo: "Sem resultado", cor: "red" };
  return (
    <Badge color={selo.cor} variant="light" size="sm">
      {selo.rotulo}
    </Badge>
  );
}

export function SeloPersistencia({ valor, motivo }: { valor: string | null; motivo?: string | null }) {
  const selo = (valor && PERSISTENCIA[valor]) || { rotulo: "Sem gravação", cor: "red" };
  const badge = (
    <Badge color={selo.cor} variant="light" size="sm">
      {selo.rotulo}
    </Badge>
  );
  return motivo ? <Tooltip label={motivo}>{badge}</Tooltip> : badge;
}

export function SeloSituacao({ situacao }: { situacao: SituacaoLote }) {
  const selo = SITUACAO[situacao];
  const viva = situacao === "em_andamento" || situacao === "parando";
  return (
    <Badge
      color={selo.cor}
      variant={viva ? "filled" : "light"}
      leftSection={viva ? <Loader size={10} color="white" /> : undefined}
    >
      {selo.rotulo}
    </Badge>
  );
}

/** Sim, Não ou traço, para os indicadores booleanos da tabela. */
export function SimNao({ valor }: { valor: boolean | null | undefined }) {
  if (valor === true) return <Badge color="tim" variant="light" size="sm">Sim</Badge>;
  if (valor === false) return <span>Não</span>;
  return <span className="bpr-apagado">–</span>;
}
