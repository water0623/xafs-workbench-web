use strict;
use warnings;
use JSON::PP;
use Demeter;

my ($input, $xmu, $norm, $chi, $rfile, $meta,
    $e0, $pre1, $pre2, $nor1, $nor2, $rbkg,
    $kmin, $kmax, $dk, $window, $kweight) = @ARGV;

die "demeter_process.pl: missing arguments\n" unless defined $kweight;

my $data = Demeter::Data->new(
    file      => $input,
    name      => 'XAFS Workbench input',
    data_type => 'xmu',
);
$data->set(
    bkg_e0      => $e0,
    bkg_pre1    => $pre1,
    bkg_pre2    => $pre2,
    bkg_nor1    => $nor1,
    bkg_nor2    => $nor2,
    bkg_rbkg    => $rbkg,
    bkg_kw      => $kweight,
    bkg_flatten => 1,
    fft_kmin    => $kmin,
    fft_kmax    => $kmax,
    fft_dk      => $dk,
    fft_kwindow => $window,
);
$data->po->kweight($kweight);
$data->save('xmu',  $xmu);
$data->save('norm', $norm);
$data->save('chi',  $chi);
$data->save('r',    $rfile);

open my $fh, '>:encoding(UTF-8)', $meta or die "cannot write $meta: $!";
print {$fh} encode_json({
    e0        => 0 + $data->bkg_e0,
    edge_step => 0 + $data->bkg_step,
    backend   => 'Demeter/IFEFFIT',
});
close $fh;
