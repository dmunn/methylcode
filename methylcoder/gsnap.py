import sys
import os.path as op
from methylcoder import is_up_to_date_b, CPU_COUNT, bin_paths_from_fasta, \
        get_counts, _update_conversions, write_files
from subprocess import Popen
from pyfasta import Fasta

# /opt/src/gmap/gmap-2010-03-09/util/gmap_setup -D ../ -d hg19e_gmap  ../hg19e.f
def gmap_setup(gsnap_dir, out_dir, ref_fasta):
    ref_fasta  = op.abspath(ref_fasta)
    ref_base = op.splitext(ref_fasta)[0]
    ref_name = op.basename(ref_base)
    make_path = "Makefile.%(ref_name)s" % locals()
    gsnap_setup = op.join(gsnap_dir, "util", "gmap_setup")
    out_dir = op.abspath(out_dir)
    # have to cd to the out_dir because gsnap writes to cwd.
    cmd = "\n cd %(out_dir)s && \n"
    cmd += gsnap_setup
    cmd += " -D %(out_dir)s -o %(make_path)s -d %(ref_base)s %(ref_fasta)s > %(out_dir)s/gmap_setup.log && "
    cmd += "\n make -f %(make_path)s coords > gmap_coords.log && "
    cmd += "\n make -f %(make_path)s gmapdb > gmap_gmapdb.log &&"
    cmd += "\n %(gsnap_dir)s/src/cmetindex -d %(ref_name)s -D %(out_dir)s > gmap_cmetindex.log"
    cmd %= locals()
    print >>sys.stderr, "[ command ] $", cmd
    cmd_last = op.join(out_dir, "ran_gsnap_setup.sh")
    if not op.exists(cmd_last) or not is_up_to_date_b(ref_fasta, cmd_last):
        fh = open(cmd_last, "w")
        print >>fh, cmd
        fh.close()
    elif is_up_to_date_b(ref_fasta, cmd_last) and cmd.strip() != open(cmd_last).read().strip():
        fh = open(cmd_last, "w")
        print >>fh, cmd
        fh.close()
    if not op.exists(op.join(out_dir, make_path)) or not (is_up_to_date_b(op.join(out_dir, make_path), cmd_last)):
        # TODO ^ add check for cmetindex files as well.
        p = Popen(cmd.replace('\n', ' '), shell=True)
        print >>sys.stderr, "^ executing gmap/gsnap setup^"
        if p.wait() != 0:
            pclean = Popen("cd %(out_dir)s; make -f %(make_path)s clean" % locals())
            pclean.wait()
            pass
    else:
        print >>sys.stderr, "^ NOT executing gmap/gsnap setup. everything is up to date.^"
    return ref_base

def run_gsnap(gsnap_dir, out_dir, ref_fasta, reads_fasta, cpu_count=CPU_COUNT):
    #/opt/src/gmap/gmap-2010-03-09/src/gsnap --npaths 1 --quiet-if-excessive -A sam --nofails --nthreads 4 -D ./ -d hg19e_gmap --cmet bs_reads.fasta > bs.align.sam
    ref_base = op.splitext(ref_fasta)[0]
    ref_name = op.basename(ref_base)
    reads_fasta = op.abspath(reads_fasta)
    log = op.join(out_dir, "gsnap_run.log")

    out_sam = op.abspath(op.join(out_dir, "methylcoder.gnsap.sam"))
    cmd = "%(gsnap_dir)s/src/gsnap --npaths 1 --quiet-if-excessive -A sam "
    cmd += " --nofails --nthreads %(cpu_count)i -D %(out_dir)s"
    cmd += " -d %(ref_name)s --cmet %(reads_fasta)s > %(out_sam)s 2> %(log)s"
    cmd %= locals()
    cmd_path = op.join(out_dir, "ran_gsnap.sh")
    if not (op.exists(cmd_path) and open(cmd_path).read().strip() == cmd):
        fh = open(cmd_path, "w")
        print >>fh, cmd
        fh.close()
    print >>sys.stderr, "\n" + cmd
    if is_up_to_date_b(reads_fasta, out_sam) and is_up_to_date_b(reads_fasta, cmd_path):
        print >>sys.stderr, "^ NOT executing gsnap. everything is up to date.^"
    else:
        print >>sys.stderr, "^ executing gsnap. ^"
        p = Popen(cmd.replace('\n', ' '), shell=True)
        p.wait()
    return out_sam

def fastq_to_gsnap_fasta(out_dir, reads):
    fa_name = out_dir + "/" + op.basename(reads[0]).rstrip("_1") + ".fasta"
    if is_up_to_date_b(reads[0], fa_name) and is_up_to_date_b(reads[1], fa_name):
        print >>sys.stderr, "using existing fasta"
        return fa_name
    out_fa = open(fa_name, "w")

    fh1 = open(reads[0])
    fh2 = open(reads[1]) if len(reads) > 1 else None
    read1 = fh1.readline
    read2 = fh2.readline if fh2 is not None else None
    while True:
        header1 = read1().strip()
        if header1 == "": break
        assert header1[0] == "@"
        seq1 = read1()
        read1(); read1()
        print >>out_fa, ">" + header1[1:]
        print >>out_fa, seq1,

        if fh2 is not None:
            header2 = read2()
            assert header2.startswith(header1[:-4])
            seq2 = read2()
            print >>out_fa, seq2,
            read2(); read2()
    return fa_name

def parse_gsnap_sam(gsnap_f, ref_path, out_dir):
    fa = Fasta(ref_path)

    fc, ft, fmethyltype = \
            bin_paths_from_fasta(fa.fasta_name, out_dir)
    counts = get_counts(fc, ft, fa)
    print >>sys.stderr, "tabulating methylation"

    for sline in open(gsnap_f):
        if sline.startswith("@SQ"): continue
        # the ends didn't map to same spot.
        if not "=" in sline: continue

        line = sline.split("\t")
        if not line[6] == "=": continue
        seqid = line[2]
        sam_flag = int(line[1])
        aln_seq = line[9]
        bp0 = int(line[3])
        end = int(line[7])
        bp1 = bp0 + len(aln_seq) - 1
        ga = ((sam_flag & 16) != 0) ^ (sam_flag & 128 != 0)

        ref_seq = (fa[seqid][bp0 - 1:bp1]).upper()
        letters = 'GA' if ga else 'CT'

        _update_conversions(ref_seq, aln_seq, bp0, letters, counts[seqid]['c'], counts[seqid]['t'], 5, len(ref_seq))
    write_files(fa.fasta_name, out_dir, counts)

def main(out_dir, ref_fasta, reads, gsnap_path):
    bsnap_fasta = fastq_to_gsnap_fasta(out_dir, reads)
    gmap_setup(gsnap_path, out_dir, ref_fasta)
    gsnap_sam = run_gsnap(gsnap_path, out_dir, ref_fasta, bsnap_fasta, cpu_count=CPU_COUNT)

    parse_gsnap_sam(gsnap_sam, ref_fasta, out_dir)
