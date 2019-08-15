import os, logging
import numpy as np
import matplotlib.pyplot as plt
logging.getLogger('matplotlib').setLevel(logging.WARNING)
from crispr_tools import tabulate_score, tabulate_mageck
# from scipy import stats
# import seaborn as sns
# from pathlib import Path
try:
    from adjustText import adjust_text
except ModuleNotFoundError:
    def adjust_text(*args, **kwargs):
        pass
from typing import List, Union, Dict, Collection, Iterable, Tuple
from pathlib import Path, PosixPath, WindowsPath
import pandas as pd
import multiprocessing as mp



def _resamp(samp_total, count1D:pd.Series):
    #print(count1D.name, 'starting')
    resampsamp = np.random.choice(
        range(count1D.shape[0]),
        samp_total,
        p=count1D / sum(count1D)
    )

    # bincount acts like Counter if you pass it a list of integers with values of 0-to-len(thing)
    binned = np.bincount(resampsamp)
    # The binned array will only be as long as the maximum index that was sampled
    # fix by padding with zeros
    binlen, tablen = binned.shape[0], count1D.shape[0]
    if binlen < tablen:
        binned = np.concatenate([binned, np.zeros(tablen - binlen)])
    #print(count1D.name, 'finished')
    return binned

def resample_table_by_fraction(count_tab:pd.DataFrame, fraction:float, processors=1,
                               index_name='guide') -> pd.DataFrame:
    """return a DF with counts resampled to total the fraction supplied.
    count_tab cannot contain 'gene' or other non-numeric columns."""

    str_cols = count_tab.columns[count_tab.iloc[0, :].apply(type) == str]
    str_series = {c:count_tab[c] for c in str_cols}

    starting_cols = list(count_tab.columns)

    #count_tab.index = range(count_tab.shape[0])

    count_tab.drop(str_cols, 1, inplace=True)

    # First resamples number of reads per physical sample, then guide counts per sample
    sz = int(count_tab.sum().sum() * fraction)
    weights = count_tab.sum() / count_tab.sum().sum()
    colinds = np.random.choice(range(count_tab.shape[1]), sz, p=weights)
    colcounts = np.bincount(colinds)

    resamped_tab = {}
    with mp.Pool(processors) as pool:
        for smp_total, smp in zip(colcounts, count_tab.columns):
            resamped_tab[smp] = pool.apply_async(_resamp, args=(smp_total, count_tab[smp]))
        resamped_tab = {k:p.get() for k, p in resamped_tab.items()}
    resamped_tab = pd.DataFrame(resamped_tab, columns=count_tab.columns, index=count_tab.index)
    # resamped_tab.insert(0, index_name, count_tab.index)
    # resamped_tab.set_index(index_name, inplace=True)
    for col in str_cols:
        # position should work because we're going left to right
        pos = starting_cols.index(col)
        resamped_tab.insert(pos, col, str_series[col], )

    #resamped_tab.set_index('guide', inplace=True)

    return resamped_tab

def int2az(x):
    """count using leters a-z"""
    digits = [chr(i) for i in range(97, 95+28)]
    base = len(digits)
    if x < 0:
        return "-" + int2az(-x)
    return ("" if x < base else int2az(x // base)) + digits[x % base]

def resample_and_run_jacks(count_tab:pd.DataFrame,
                           repmap_fn:Union[str, os.PathLike],
                           fractions:List[float],
                           nreps:int,
                           tabulate:True,
                           working_dir:Union[str, os.PathLike],
                           processors:int=None,
                           jacks_kwargs=None) -> Dict[float, Dict[str, pd.DataFrame]]:
    """Run a resampling experiment. The count_tab is resampled, to size
    given in fractions, nreps times per fraction. Returns dict of dict of DF
    prodcued by tabulate_score, keyed first by fraction and then rep letter.

    repmap is in the JACKS format."""
    #todo make work with other analyses
    from jacks.jacks_io import runJACKS
    from jacks.infer import LOG as jacksLOG
    jacksLOG.setLevel(logging.WARNING)


    if jacks_kwargs is None:
        jacks_kwargs = {}
    jkwgs = dict(ctrl_sample_hdr='ctrl', gene_hdr='gene', sgrna_hdr='guide')
    jkwgs.update(jacks_kwargs)
    if processors is None:
        processors = mp.cpu_count()
        if processors > 1:
            processors -= 1

    assert os.path.isdir(working_dir)
    resamped_tabs = {}

    def _rep_iter():
        for _rep in range(nreps):

            _letter = int2az(_rep)
            for _frac in fractions:
                _k = str(_frac) + _letter
                yield _frac, _letter, _k

    # tables will be keyed by fraction and letters starting with 'a' per rep
    for frac, letter, k in _rep_iter():
        resamped_tabs[k] = resample_table_by_fraction(count_tab.copy(), frac, processors)

    tables = {f:{} for f in fractions}

    for frac, letter, k in _rep_iter():
        tab = resamped_tabs[k]
        tabpath = f"{working_dir}/count_{k}.tsv"
        tab.to_csv(tabpath, '\t')
        respath = f"{working_dir}/jacks_{k}"
        runJACKS(tabpath, repmap_fn, tabpath, 'rep', 'samp', outprefix=respath, **jkwgs)
        if tabulate:
            tables[frac][letter] = tabulate_score(respath,return_ps=True)

    if tabulate:
        return tables
    else:
        return None

def calc_stability(tables=Dict[float, Dict[str, pd.DataFrame]],
                   score_key='jacks_score', ):
    """Stability is the stdev per gene across multiple resampled
    replicates at different fractions. The median of these are taken per
    sample per fraction.

    Returns DF with fractions as column index, and samples as row index."""
    all_ys = {}
    fractions = list(tables.keys())
    samples = tables[fractions[0]]['a'].columns.levels[0]

    out_df = pd.DataFrame(index=fractions, columns=samples)

    for samp in samples:
        for frac, reps in tables.items():
            # scores is a by rep dict of scores
            scores = {k:tab[samp][score_key] for k, tab in reps.items()}
            # cast to df to get the median stdev across the reps
            out_df.loc[frac, samp] = pd.DataFrame(scores).std(1).median()

    return out_df


def plot_stability(ys_df, ax:plt.Axes=None):

    if ax is None:
        ax = plt.gca()
    else:
        plt.sca(ax)
    ys_df.plot(alpha=0.4, legend=False)
    ys_df.mean(1).plot(marker='o', color='k')
    plt.ylim(0)
    plt.xlabel('Proportion of total reads')
    plt.ylabel('Median stdev of resampled gene scores, per sample')
    plt.tight_layout()
    return ax


def test_resampling():

    print(os.getcwd())
    tab = pd.read_table('tests/test_counts.tsv', index_col=0)
    repmap =  'tests/run_testD3.repmap.tsv'
    tables = resample_and_run_jacks(
        tab,
        repmap_fn=repmap,
        fractions=[0.1,0.2],
        nreps=2,
        tabulate=True,
        working_dir='tests/resample_out',
        processors=4
    )

    yz = calc_stability(tables)
    ax = plot_stability(yz)
    plt.show()

if __name__ == '__main__':
    test_resampling()
