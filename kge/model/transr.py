import torch
from kge import Config, Dataset
from kge.model.kge_model import RelationalScorer, KgeModel
from torch.nn import functional as f


class TransRScorer(RelationalScorer):
    r"""Implementation of the TransR KGE scorer."""

    def __init__(self, config: Config, dataset: Dataset, configuration_key=None):
        super().__init__(config, dataset, configuration_key)
        self._norm = self.get_option("l_norm")

    def _transfer(self, ent_emb, rel_emb, projection_matrix):
        n = rel_emb.size(0)
        k = ent_emb.size(1)
        d = rel_emb.size(1)

        ent_emb = ent_emb.view(n, k, 1)
        projection_matrix = projection_matrix.view(n, d, k)

        out = torch.matmul(projection_matrix, ent_emb)

        return out.reshape(-1, d)

    def score_emb(self, s_emb, p_emb, o_emb, combine: str):
        test = torch.chunk(p_emb, 129, dim=1)

        rel_emb = test[0]
        projection_matrix = torch.cat(test[-(len(test)-1):])

        n = p_emb.size(0)
        if combine == "spo":
            # n = n_s = n_p = n_o
            s_emb_translated = self._transfer(s_emb, rel_emb, projection_matrix)
            o_emb_translated = self._transfer(o_emb, rel_emb, projection_matrix)

            out = -f.pairwise_distance(s_emb_translated + rel_emb, o_emb_translated, p=self._norm)
        elif combine == "sp_":
            # n = n_s = n_p != n_o = m
            m = o_emb.size(0)

            s_emb_translated = self._transfer(s_emb, rel_emb, projection_matrix)
            s_emb_translated = s_emb_translated.repeat(m, 1)

            rel_emb = rel_emb.repeat(m, 1)
            projection_matrix = projection_matrix.repeat(m, 1)

            o_emb = o_emb.repeat_interleave(n, 0)
            o_emb_translated = self._transfer(o_emb, rel_emb, projection_matrix)

            out = -f.pairwise_distance(s_emb_translated + rel_emb, o_emb_translated, p=self._norm)
            out = out.view(m, n).transpose(0, 1)
        elif combine == "_po":
            # m = n_s != n_p = n_o = n
            m = s_emb.size(0)

            o_emb_translated = self._transfer(o_emb, rel_emb, projection_matrix)
            o_emb_translated = o_emb_translated.repeat(m, 1)

            rel_emb = rel_emb.repeat(m, 1)
            projection_matrix = projection_matrix.repeat(m, 1)

            s_emb = s_emb.repeat_interleave(n, 0)
            s_emb_translated = self._transfer(s_emb, rel_emb, projection_matrix)

            out = -f.pairwise_distance(o_emb_translated - rel_emb, s_emb_translated, p=self._norm)
            out = out.view(m, n).transpose(0, 1)
        else:
            return super().score_emb(s_emb, p_emb, o_emb, combine)

        return out.view(n, -1)


class TransR(KgeModel):
    r"""Implementation of the TransR KGE model."""

    def __init__(
            self,
            config: Config,
            dataset: Dataset,
            configuration_key=None,
            init_for_load_only=False,
    ):
        self._init_configuration(config, configuration_key)

        transr_set_relation_embedder_dim(
            config, dataset, self.configuration_key + ".relation_embedder"
        )

        super().__init__(
            config=config,
            dataset=dataset,
            scorer=TransRScorer,
            configuration_key=self.configuration_key,
            init_for_load_only=init_for_load_only,
        )


def transr_set_relation_embedder_dim(config, dataset, rel_emb_conf_key):
    """Set the relation embedder dimensionality for TransR in the config.

    Dimensionality must be double the size of the entity embedder dimensionality.

    """
    ent_emb_conf_key = rel_emb_conf_key.replace(
        "relation_embedder", "entity_embedder"
    )
    if ent_emb_conf_key == rel_emb_conf_key:
        raise ValueError(
            "Cannot determine relation embedding size. "
            "Please set manually to double the size of the "
            "entity embedder dimensionality."
        )
    # TODO: ensure that ent_emb.dim modulo 2 is 0 -> otherwise the *64.5 will result in an error
    dim = int(config.get_default(ent_emb_conf_key + ".dim") * 64.5)
    config.set(rel_emb_conf_key + ".dim", dim, log=True)
