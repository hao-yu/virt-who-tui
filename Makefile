install:
	python setup.py install

tito_srpm:
	tito build --srpm --test

tito_rpm:
	tito build --rpm --test

rpm:
	python setup.py bdist_rpm --requires "python-urwid virt-who"
