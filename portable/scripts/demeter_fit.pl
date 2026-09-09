use strict;
use warnings;
use JSON::PP;
use File::Basename qw(dirname basename);
use Demeter;

my ($config_file) = @ARGV;
die "demeter_fit.pl: missing configuration file\n" unless defined $config_file;

open my $cfg_fh, '<:encoding(UTF-8)', $config_file or die "cannot read $config_file: $!";
my $cfg;
{
    local $/;
    $cfg = decode_json(<$cfg_fh>);
}
close $cfg_fh;

my $data = Demeter::Data->new(
    file      => $cfg->{chi_file},
    name      => $cfg->{data_name} || 'XAFS Workbench data',
    # Demeter's actual attribute is "datatype".  "data_type" is silently
    # ignored by older releases, causing chi(k) to be treated as mu(E) and
    # triggering the irrelevant Rmin < AUTOBK rbkg fit sanity error.
    datatype  => 'chi',
);
$data->set(
    fft_kmin    => 0 + $cfg->{kmin},
    fft_kmax    => 0 + $cfg->{kmax},
    fft_dk      => 0 + $cfg->{dk},
    fft_kwindow => $cfg->{window},
    bft_rmin    => 0 + $cfg->{rmin},
    bft_rmax    => 0 + $cfg->{rmax},
    bft_rwindow => $cfg->{rwindow},
    fit_space   => $cfg->{fitspace},
    fit_do_bkg  => 0,
    fit_k1      => 0,
    fit_k2      => 0,
    fit_k3      => 0,
);
for my $kw (@{$cfg->{kweights}}) {
    $data->fit_k1(1) if $kw == 1;
    $data->fit_k2(1) if $kw == 2;
    $data->fit_k3(1) if $kw == 3;
}
$data->po->kweight(0 + $cfg->{display_kweight});

my @gds;
for my $item (@{$cfg->{gds}}) {
    push @gds, Demeter::GDS->new(
        gds     => $item->{type},
        name    => $item->{name},
        mathexp => $item->{value},
    );
}

my @paths;
for my $item (@{$cfg->{paths}}) {
    die "FEFF path file is not readable: $item->{file}\n" unless -f $item->{file};
    open my $probe_fh, '<', $item->{file} or die "cannot inspect FEFF path: $!";
    my ($probe_header, $probe_geometry) = (0, q{});
    while (<$probe_fh>) {
        if (m{\A\s*-------}) { $probe_header = 1; next; }
        next unless $probe_header;
        last if m{\A\s+k\s+real};
        $probe_geometry .= $_;
    }
    close $probe_fh;
    my @probe_values = split(' ', $probe_geometry);
    die "FEFF path geometry header was not recognized: [$probe_geometry]\n" unless @probe_values >= 3;
    my $path = Demeter::Path->new(data => $data);
    # Path::file parses feffNNNN.dat immediately, so the folder must already
    # be set.  Passing both through a single hash is order-dependent in Perl.
    $path->folder(dirname($item->{file}));
    $path->file(basename($item->{file}));
    $path->set(
        name   => $item->{label},
        s02    => $item->{s02},
        e0     => $item->{e0},
        sigma2 => $item->{sigma2},
        delr   => $item->{delr},
    );
    push @paths, $path;
}

my $fit = Demeter::Fit->new(
    gds       => \@gds,
    data      => [$data],
    paths     => \@paths,
    interface => 'XAFS Workbench native Demeter/IFEFFIT bridge',
    cormin    => 0.1,
);
$fit->fit;
$fit->evaluate;

$data->save('fit', $cfg->{fit_k_file});
$data->save('fit', $cfg->{fit_rmag_file}, 'rmag');
$data->save('fit', $cfg->{fit_rre_file},  'rre');
$data->save('fit', $cfg->{fit_rim_file},  'rim');
$fit->logfile($cfg->{log_file});

my @parameters;
for my $item (@gds) {
    push @parameters, {
        name    => $item->name,
        state   => $item->gds,
        initial => $item->mathexp,
        value   => 0 + $item->bestfit,
        error   => 0 + ($item->error || 0),
    };
}

my @path_results;
for my $index (0 .. $#paths) {
    my $path = $paths[$index];
    push @path_results, {
        index        => $index + 1,
        label        => $path->name,
        degeneracy   => 0 + $path->n,
        reff          => 0 + $path->reff,
        s02_value     => 0 + $path->s02_value,
        e0_value      => 0 + $path->e0_value,
        sigma2_value  => 0 + $path->sigma2_value,
        delr_value    => 0 + $path->delr_value,
    };
}

my @correlations;
for my $left ($fit->keys_in_correlations) {
    my $values = $fit->get_correlations($left);
    for my $right (keys %{$values}) {
        push @correlations, {
            parameter_1 => $left,
            parameter_2 => $right,
            correlation => 0 + $values->{$right},
        };
    }
}

open my $out_fh, '>:encoding(UTF-8)', $cfg->{result_file}
    or die "cannot write $cfg->{result_file}: $!";
print {$out_fh} encode_json({
    backend             => 'Demeter/IFEFFIT',
    parameters          => \@parameters,
    paths               => \@path_results,
    correlations        => \@correlations,
    r_factor            => 0 + $fit->r_factor,
    chi_square          => 0 + $fit->chi_square,
    reduced_chi_square  => 0 + $fit->chi_reduced,
    n_variables         => 0 + $fit->n_varys,
    n_independent       => 0 + $fit->n_idp,
});
close $out_fh;
