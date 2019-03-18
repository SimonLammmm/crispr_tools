#!Python3
import os, sys
from collections import Counter
import gzip
import argparse
from pathlib import Path, PosixPath, WindowsPath

from typing import List

"""Functions for counting and mapping reads from multiple FASTQ files
to some kind of sequence library, e.g. a CRISPR guide library. 
Assumes that FQ filenames are in the format {sample_name}_L???_R1_001.fastq[.gz]
and that the sequence to be mapped is in the same position in every read.
It's probably not very useful if either of these things are false.

Produces dereplicated sequence counts (one file per sample) and then a single
file containing reads mapped to guide/gene from a library file."""

__version__ = '1.3.2'
# 1.3.2 Bugfixes, documentation
# 1.3.1 returned column order of map_counts now 'guide', 'gene', [everything else]
#       fixed splitter issue
# v1.3.0 added map_counts
# v1.2.4 added printed info explaining sample merges.
# v1.2.3 changed func name to count_reads, added import to __init__, renamed to crispr_tools
# v1.2.2 bugfixes, started using pathlib, reimplimented ability to pass dir
# v1.2.1
#   added option to pass substring to slicer which will be used to start cutting
#   no longer checks line number/4 == sequences counted
# v1.2 filename prefix, removed directory walking, added merge_samples, removed merge_lanes
# v1.1 added argument parsing, options to merge lanes

#todo just ouput a single file
#todo use **kwargs to pass parsed args to count_batch
#todo use logging instead of stealing print


def count_reads(fn, slicer=(None, None), s_len=None, s_offset=0, ):
    """Count single .fq reads. Use count_batch for multiple files.
    Slicer should be a tuple of indicies.
    Returns a Counter.

    s_len and s_offset are depreciated, use Cutadapt instead.
    """
    if type(slicer[0]) == int:
        chop = slice(*slicer)
    seqs = Counter()
    lns = 0
    failed_count = 0
    if fn.endswith('.gz'):
        f = gzip.open(fn, 'rt')
    else:
        f = open(fn)
    for line in f:
        lns += 1
        if line[0] == '@':
            s = f.__next__()
            s = s.replace('\n', '')
            lns+=1
            if s_len is None:
                s = s[chop]
            else:
                try:
                    i = s.index(slicer)+s_offset
                    s = s[i:i+s_len]
                except:
                    failed_count+=1
                    continue
            seqs[s] += 1
    f.close()
    print(fn, len(seqs), 'sequences counted.')
    if s_len is not None:
        print(failed_count, 'sequences did not contain subsequence')
    return seqs

def get_file_list(files_dir) -> List[os.PathLike]:
    """Pass single string or list of stings, strings that are files go on the
    file list, directories will have all files within (not recursive) will be
    added to the file list.

    A list of Path obj are returned."""

    file_list = []
    # just in case trying to make a list of a single string...
    if type(files_dir) in (str, PosixPath, WindowsPath):
        files_dir = [files_dir]
    # convert to Path
    files = [Path(f) for f in files_dir]
    # get single list of Path, containing all listed files and files in listed dir
    # dir within `files` will be ignored.
    for fndir in files:
        if os.path.isdir(fndir):
            for fn in os.listdir(fndir):
                fn = fndir/fn
                if os.path.isfile(fn):
                    file_list.append(fn)
        else:
            file_list.append(fndir)
    file_list = [fn for fn in file_list if fn.name[0] != '.']
    return file_list


def count_batch(fn_or_dir, slicer, fn_prefix='', seq_len=None, seq_offset=0, fn_suffix='.rawcount',
                fn_split='_R1_', merge_samples=False, just_go=False, quiet=False,
                allowed_extensions = ('.fastq', 'fastq.gz', '.fq')):
    """Write a table giving the frequency of all unique sequences from a fastq
    files (or fastq.gz).

    Output filenames are derived from input filenames. Outfn are returned.

    Merge_samples looks for file names containing "_L001_" and assumes all
    files with the same prefix are the same sample.

    Arguments:
        fn_or_dir:
            A list of files or dir. All files in given dir that end
            with .fastq or .fastq.gz or .fq will be counted.

        slicer (M,N)|subseq:
            Slice indicies to truncate sequences (zero indexed,
            end exclusive). Comma-sep ints.
            OR a subsequence from which slicing will happen.

        seq_len (int):
            Required when slicer is a sequence, determines output sequence
            lengths.

        fn_prefix:
            Prefix added to output files, can include absolute or
            relative paths.

        fn_suffix:
            Suffix added to output files, .txt added after. Default `rawcount`

        fn_split:
            String used to split filenames and form output file prefix.
            Default `_R1_`. Doesn't do anything if --merge-samples is used.

        merge_samples:
            Merge counts from files with identical sample names. Be
            careful not to double count decompressed & compressed files. Bool.

        allowed_extensions  ('fastq', 'fastq.gz', '.fq')
    """
    global print
    if quiet:
        print = lambda x: None
        just_go = True
    else:
        print = print

    # accepts list of mixed files and dir, ends up as list of files
    file_list = get_file_list(fn_or_dir)

    # filter the file list
    # strings are easier to work with at this point
    file_list = [str(f) for f in file_list]
    file_list = [ f for f in file_list if any([f.endswith(suf) for suf in allowed_extensions])]

    # map filenames to samples
    if merge_samples:
        samples = set([f.split('_L001_')[0].split('/')[-1] for f in file_list if '_L001_' in f])

        file_dict = {s:[f for f in file_list if s in f] for s in samples}
        print('Samples found:',)
        for k,v in file_dict.items():
            print(k)
            for f in v:
                print('\t'+f)
    else:
        print('input files')
        print('\n'.join(file_list))

    if type(slicer[0]) is int:
        lengthstring = 'Length={}'.format(slicer[1]-slicer[0])
    else:
        lengthstring = 'Length={}'.format(seq_len)
    if not just_go:
        input(lengthstring+'\nPress enter to go...')
    else:
        print(lengthstring, '\n')

    # called in the main loop
    def write_count(a_cnt, fn_base):
        if fn_prefix:
            if fn_prefix[-1] == '/':
                fs = '{}{}{}.txt'
            else:
                fs = '{}.{}{}.txt'
            outfn = fs.format(fn_prefix, fn_base, fn_suffix)
        else:
            outfn = '{}.{}.txt'.format(fn_base, fn_suffix)
        with open(outfn, 'w') as f:
            for s, n in a_cnt.most_common():
                f.write('{}\t{}\n'.format(s,n))
        return outfn
    # used if library mapping being done
    out_files = []

    # main loop(s)
    if merge_samples:
        for samp, fn_or_dir in file_dict.items():
            cnt = Counter()
            for fn in fn_or_dir:
                cnt += count_reads(fn, slicer, seq_len, seq_offset)
            out_files.append(
                write_count(cnt, samp)
            )
    else:
        for fn in file_list:
            cnt = count_reads(fn, slicer, seq_len, seq_offset)
            out_files.append(
                write_count(cnt, fn.split(fn_split)[0].split('/')[-1])
            )

    return out_files

def map_counts(fn_or_dir, lib, guidehdr='guide', genehdr='gene',
               drop_unmatched=False, report=False, splitter='.raw',
               remove_text = '', out_fn=None):
    """lib needs to be indexed by guide sequence. If it's not a DF a DF will
    be loaded and indexed by 'seq' or the first column. Returns a DF indexed
    by 'guide' with 'gene' as the second column.

    """

    import pandas as pd
    if type(lib) in (str, PosixPath, WindowsPath):
        lib = str(lib)
        if lib.endswith('.csv'):
            sep = ','
        else:
            sep = '\t'
        lib = pd.read_csv(lib, sep)
        if 'seq' in lib.columns:
            lib.set_index('seq', drop=False, inplace=True)
        else:
            lib.set_index(lib.columns[0])
    # else the library should be in a sueable form.

    # write a single table
    file_list = get_file_list(fn_or_dir)
    file_list = [f for f in file_list if splitter in str(f)]
    print(file_list)
    rawcnt = pd.DataFrame()

    # get single table of counts
    for fn in file_list:
        # filtering of fn done before here
        rawcnt.loc[:, fn.name.split(splitter)[0]] = pd.read_table(fn, index_col=0, header=None).iloc[:, 0]

    rawcnt = rawcnt.fillna(0).astype(int)
    # the abscent guides
    missing = lib.loc[~lib.index.isin(rawcnt.index), :].index

    # get the present guides
    matches = rawcnt.loc[rawcnt.index.isin(lib.index), :].index
    if report:
        prop = rawcnt.loc[matches, :].sum().sum()/rawcnt.sum().sum()
        print("{:.3}% of reads map.".format(prop*100))
        print("{:.3}% ({}) of library guides not found.".format(
            missing.shape[0] / lib.shape[0] *100, missing.shape[0]
        ))
    #cnt = rawcnt.loc[matches, :].copy()
    rawcnt.loc[matches, 'guide'] = lib.loc[matches, guidehdr]
    rawcnt.loc[matches, 'gene'] = lib.loc[matches, genehdr]

    missingdf = pd.DataFrame(index=missing, columns=rawcnt.columns)
    missingdf.loc[:, :] = 0
    missingdf.loc[missing, 'guide'] = lib.loc[missing, guidehdr]
    missingdf.loc[missing, 'gene'] = lib.loc[missing, genehdr]
    rawcnt = rawcnt.append(missingdf)

    if drop_unmatched:
        cnt = rawcnt.loc[lib.index, :].copy()
    else:
        cnt = rawcnt

    # sort out columns
    cols = list(cnt.columns)
    cnt = cnt.reindex([guidehdr, genehdr] + cols[:-2], axis='columns',)
    cnt.set_index(guidehdr, inplace=True)

    if out_fn:
        cnt.to_csv(out_fn, sep='\t')
    return cnt





# os.chdir('/Users/johnc.thomas/thecluster/jct61/counts/nomask')
# map_counts(
#     'tst', '/Users/johnc.thomas/thecluster/jct61/crispr_libraries/Kinase_gRNA_library_no_duplicates.csv',
#     drop_unmatched=True, report=True, out_fn='tst/tstout2.tsv'
#
# )

if __name__ == '__main__':
    print('v', __version__)
    parser = argparse.ArgumentParser(description='Count unique sequences in FASTQs. Assumes filenames are {sample_name}_L00?_R1_001.fastq[.gz]')
    parser.add_argument('files', nargs='+',
                        help="A list of files or dir. All files in given dir that end with .fastq or .fastq.gz or .fq will be counted.")
    parser.add_argument('-s', metavar='M,N',
                        help='Slice indicies to truncate sequences (zero indexed, not end-inclusive). Comma-sep numbers. Required.',
                        required=True)
    parser.add_argument('-f', default='.rawcount', metavar='FN_SUFFIX',
                        help="Suffix added to output files, .txt will always be added after. Default `.rawcount`")
    parser.add_argument('-p', default='', metavar='FN_PREFIX',
                        help="Prefix added to output files, can include absolute or relative paths.")
    parser.add_argument('--fn-split', default='_R1_', metavar='STR',
                        help="String used to split filenames and form output file prefix. Default `_R1_`." \
                             "Doesn't do anything if --merge-samples is used.")
    parser.add_argument('--merge-samples', action='store_true', default=False,
                        help="Merge counts from files with identical sample names.")
    parser.add_argument('--just-go', action='store_true', default=False, help="Don't wait for confirmation.")
    parser.add_argument('--quiet', action='store_true', default=False, help="Don't print helpful messages, enables --just-go.")
    parser.add_argument('--library', default=None, metavar='LIB_PATH',
                        help="Pass a library file and a single mapped reads count file will be output with" \
                             "the name [FN_PREFIX].counts.tsv")
    clargs = parser.parse_args()

    # slices list of input files, or dir
    slicer = [int(n) for n in clargs.s.split(',')]

    written_fn = count_batch(clargs.files, slicer, clargs.p, None, 0, clargs.f, clargs.fn_split, clargs.merge_samples,
                clargs.just_go, clargs.quiet)
    if clargs.library:
        # remove file prefix
        fpref = Path(clargs.p).stem.split('.')[1]
        map_counts(written_fn, clargs.library, drop_unmatched=True, report=True, remove_text=fpref,
                   out_fn=clargs.p+'.counts.tsv', splitter=clargs.f)



