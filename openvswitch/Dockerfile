FROM debian:buster-slim
ENV OVS_VERSION 2.13.0
RUN apt-get update && apt-get install -y python3-pip python3 python python-setuptools make autoconf wget gcc git supervisor
# Configure supervisord
RUN mkdir -p /var/log/supervisor/
ADD supervisord.conf /etc/
# Install supervisor_stdout
WORKDIR /opt
RUN mkdir -p /var/log/supervisor/
RUN mkdir -p /etc/openvswitch
RUN git clone https://github.com/coderanger/supervisor-stdout && \
	cd supervisor-stdout && \
	python setup.py install -q
# Get Open vSwitch
WORKDIR /
RUN pip3 install six
RUN wget https://www.openvswitch.org/releases/openvswitch-$OVS_VERSION.tar.gz --no-check-certificate && \
	tar -xzvf openvswitch-$OVS_VERSION.tar.gz &&\
	mv openvswitch-$OVS_VERSION openvswitch &&\
	cd openvswitch && \
	./configure && make && make install && cd .. && \
	cp -r openvswitch/* / &&\
	rm -r openvswitch &&\
	rm openvswitch-$OVS_VERSION.tar.gz
ADD configure-ovs.sh /usr/local/share/openvswitch/
RUN mkdir -p /usr/local/var/run/openvswitch
# Create the database
RUN ovsdb-tool create /etc/openvswitch/conf.db /usr/local/share/openvswitch/vswitch.ovsschema
ADD scripts /scripts
CMD ["/usr/bin/supervisord"]